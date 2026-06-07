//! Cluster-manager Handler adapter (pilot implementation of the Handler trait).
//!
//! This module implements `Handler` directly on `ClusterManagerState` so that all
//! cluster-domain logic — key dispatch, RPC-response handling, and orchestration —
//! lives in one place and is unit-testable without constructing a full `App`.
//!
//! **Render deferral:** Rendering is NOT part of the `Handler` trait for this pilot;
//! render fns remain in `src/ui/cluster_manager.rs` and still take `&App`.  Decoupling
//! render from `&App` is tracked as crystalmath-3y4.3.

use crossterm::event::{KeyCode, KeyEvent};
use tracing::debug;

use crate::bridge::{BridgeResponse, BridgeService};
use crate::handlers::{Handler, HandlerCtx};
use crate::ui::{ClusterFormField, ClusterManagerMode, ClusterManagerState, ConnectionTestResult};

// ─── Orchestration helpers (previously App methods) ───────────────────────────

impl ClusterManagerState {
    /// Request the list of clusters from the backend.
    ///
    /// Previously `App::request_fetch_clusters`.
    pub fn fetch_clusters(&mut self, bridge: &dyn BridgeService, ctx: &mut HandlerCtx) {
        let request_id = ctx.next_request_id();
        self.request_id = request_id;
        self.loading = true;
        if let Err(e) = bridge.request_fetch_clusters(request_id) {
            self.set_status(&format!("Failed to fetch clusters: {}", e), true);
            self.loading = false;
        }
        ctx.mark_dirty();
    }

    /// Request creation of a new cluster from current form data.
    ///
    /// Previously `App::create_cluster_from_form`.
    pub fn create_from_form(&mut self, bridge: &dyn BridgeService, ctx: &mut HandlerCtx) {
        match self.build_config() {
            Ok(config) => {
                let request_id = ctx.next_request_id();
                self.request_id = request_id;
                self.loading = true;
                if let Err(e) = bridge.request_create_cluster(&config, request_id) {
                    self.set_status(&format!("Failed to create cluster: {}", e), true);
                    self.loading = false;
                }
                ctx.mark_dirty();
            }
            Err(e) => {
                self.set_status(&e, true);
                ctx.mark_dirty();
            }
        }
    }

    /// Request an update to the cluster currently being edited.
    ///
    /// Previously `App::update_cluster_from_form`.
    pub fn update_from_form(&mut self, bridge: &dyn BridgeService, ctx: &mut HandlerCtx) {
        let cluster_id = match self.editing_cluster_id {
            Some(id) => id,
            None => {
                self.set_status("No cluster selected for editing", true);
                ctx.mark_dirty();
                return;
            }
        };

        match self.build_config() {
            Ok(config) => {
                let request_id = ctx.next_request_id();
                self.request_id = request_id;
                self.loading = true;
                if let Err(e) = bridge.request_update_cluster(cluster_id, &config, request_id) {
                    self.set_status(&format!("Failed to update cluster: {}", e), true);
                    self.loading = false;
                }
                ctx.mark_dirty();
            }
            Err(e) => {
                self.set_status(&e, true);
                ctx.mark_dirty();
            }
        }
    }

    /// Request deletion of the currently selected cluster.
    ///
    /// Previously `App::delete_selected_cluster`.
    pub fn delete_selected(&mut self, bridge: &dyn BridgeService, ctx: &mut HandlerCtx) {
        let cluster_id = match self.selected_cluster() {
            Some(c) => match c.id {
                Some(id) => id,
                None => {
                    self.set_status("Cluster has no ID", true);
                    ctx.mark_dirty();
                    return;
                }
            },
            None => {
                self.set_status("No cluster selected", true);
                ctx.mark_dirty();
                return;
            }
        };

        let request_id = ctx.next_request_id();
        self.request_id = request_id;
        self.loading = true;
        if let Err(e) = bridge.request_delete_cluster(cluster_id, request_id) {
            self.set_status(&format!("Failed to delete cluster: {}", e), true);
            self.loading = false;
        }
        ctx.mark_dirty();
    }

    /// Request an SSH connection test to the currently selected cluster.
    ///
    /// Previously `App::test_selected_cluster_connection`.
    pub fn test_connection(&mut self, bridge: &dyn BridgeService, ctx: &mut HandlerCtx) {
        let cluster_id = match self.selected_cluster() {
            Some(c) => match c.id {
                Some(id) => id,
                None => {
                    self.set_status("Cluster has no ID", true);
                    ctx.mark_dirty();
                    return;
                }
            },
            None => {
                self.set_status("No cluster selected", true);
                ctx.mark_dirty();
                return;
            }
        };

        let request_id = ctx.next_request_id();
        self.request_id = request_id;
        self.loading = true;
        self.connection_result = None;
        self.set_status("Testing connection...", false);
        if let Err(e) = bridge.request_test_cluster_connection(cluster_id, request_id) {
            self.set_status(&format!("Failed to test connection: {}", e), true);
            self.loading = false;
        }
        ctx.mark_dirty();
    }
}

// ─── Handler impl ──────────────────────────────────────────────────────────────

impl Handler for ClusterManagerState {
    fn is_active(&self) -> bool {
        self.active
    }

    /// Process key input for the cluster manager modal.
    ///
    /// Logic moved verbatim from `handle_cluster_manager_modal_input` (main.rs ~1154-1282)
    /// and the two helper fns `handle_cluster_form_char` / `handle_cluster_form_backspace`.
    fn handle_key(
        &mut self,
        key: KeyEvent,
        bridge: &dyn BridgeService,
        ctx: &mut HandlerCtx,
    ) -> bool {
        // Don't process input while loading (only allow Escape).
        if self.loading {
            if key.code == KeyCode::Esc {
                self.close();
                ctx.mark_dirty();
            }
            return true; // Consumed — no other handler should see keys while we're loading.
        }

        match self.mode {
            ClusterManagerMode::List => match key.code {
                KeyCode::Esc => {
                    self.close();
                    ctx.mark_dirty();
                }
                KeyCode::Char('j') | KeyCode::Down => {
                    self.select_next();
                    self.connection_result = None;
                    ctx.mark_dirty();
                }
                KeyCode::Char('k') | KeyCode::Up => {
                    self.select_prev();
                    self.connection_result = None;
                    ctx.mark_dirty();
                }
                KeyCode::Char('a') => {
                    self.start_add();
                    ctx.mark_dirty();
                }
                KeyCode::Char('e') if self.selected_index.is_some() => {
                    self.start_edit();
                    ctx.mark_dirty();
                }
                KeyCode::Char('d') if self.selected_index.is_some() => {
                    self.start_delete();
                    ctx.mark_dirty();
                }
                KeyCode::Char('t') => {
                    self.test_connection(bridge, ctx);
                }
                KeyCode::Char('r') => {
                    self.fetch_clusters(bridge, ctx);
                }
                _ => {}
            },

            ClusterManagerMode::Add | ClusterManagerMode::Edit => match key.code {
                KeyCode::Esc => {
                    self.cancel();
                    ctx.mark_dirty();
                }
                KeyCode::Enter => {
                    if self.mode == ClusterManagerMode::Add {
                        self.create_from_form(bridge, ctx);
                    } else {
                        self.update_from_form(bridge, ctx);
                    }
                }
                KeyCode::Tab | KeyCode::Down => {
                    self.focused_field = self.focused_field.next();
                    self.error = None;
                    ctx.mark_dirty();
                }
                KeyCode::BackTab | KeyCode::Up => {
                    self.focused_field = self.focused_field.prev();
                    self.error = None;
                    ctx.mark_dirty();
                }
                KeyCode::Char(' ') => {
                    if self.focused_field == ClusterFormField::ClusterType {
                        self.form_cluster_type = self.form_cluster_type.cycle();
                        ctx.mark_dirty();
                    } else {
                        cluster_form_push_char(self, ' ', ctx);
                    }
                }
                KeyCode::Backspace => {
                    cluster_form_pop_char(self, ctx);
                }
                KeyCode::Char(c) => {
                    cluster_form_push_char(self, c, ctx);
                }
                _ => {}
            },

            ClusterManagerMode::ConfirmDelete => match key.code {
                KeyCode::Char('y') | KeyCode::Char('Y') => {
                    self.delete_selected(bridge, ctx);
                }
                KeyCode::Char('n') | KeyCode::Char('N') | KeyCode::Esc => {
                    self.cancel();
                    ctx.mark_dirty();
                }
                _ => {}
            },
        }

        true // We always consume keys while the cluster modal is active.
    }

    /// Process a bridge response.
    ///
    /// Handles the six cluster-specific `BridgeResponse` variants previously handled
    /// as arms in `App::poll_bridge_responses` (app.rs ~1214-1317).
    /// Returns `true` when the response was claimed, `false` otherwise.
    fn handle_response(
        &mut self,
        resp: &BridgeResponse,
        bridge: &dyn BridgeService,
        ctx: &mut HandlerCtx,
    ) -> bool {
        match resp {
            BridgeResponse::Clusters { request_id, result } => {
                if *request_id != self.request_id {
                    return false;
                }
                self.loading = false;
                match result {
                    Ok(clusters) => {
                        let count = clusters.len();
                        self.clusters = clusters.clone();
                        if count > 0 && self.selected_index.is_none() {
                            self.selected_index = Some(0);
                        }
                        self.set_status(&format!("Loaded {} clusters", count), false);
                    }
                    Err(e) => {
                        self.set_status(&format!("Failed to load clusters: {}", e), true);
                    }
                }
                ctx.mark_dirty();
                true
            }

            BridgeResponse::Cluster { request_id, result } => {
                if *request_id != self.request_id {
                    return false;
                }
                debug!(
                    "Cluster response (request_id={}): {:?}",
                    request_id,
                    result.is_ok()
                );
                true
            }

            BridgeResponse::ClusterCreated { request_id, result } => {
                if *request_id != self.request_id {
                    return false;
                }
                self.loading = false;
                match result {
                    Ok(cluster) => {
                        self.set_status(&format!("Created cluster '{}'", cluster.name), false);
                        self.cancel(); // Return to list view.
                        self.fetch_clusters(bridge, ctx); // Refresh the list.
                    }
                    Err(e) => {
                        self.set_status(&format!("Failed to create cluster: {}", e), true);
                    }
                }
                ctx.mark_dirty();
                true
            }

            BridgeResponse::ClusterUpdated { request_id, result } => {
                if *request_id != self.request_id {
                    return false;
                }
                self.loading = false;
                match result {
                    Ok(()) => {
                        self.set_status("Cluster updated", false);
                        self.cancel(); // Return to list view.
                        self.fetch_clusters(bridge, ctx); // Refresh the list.
                    }
                    Err(e) => {
                        self.set_status(&format!("Failed to update cluster: {}", e), true);
                    }
                }
                ctx.mark_dirty();
                true
            }

            BridgeResponse::ClusterDeleted { request_id, result } => {
                if *request_id != self.request_id {
                    return false;
                }
                self.loading = false;
                match result {
                    Ok(success) => {
                        if *success {
                            self.set_status("Cluster deleted", false);
                            self.cancel(); // Return to list view.
                            self.selected_index = None;
                            self.fetch_clusters(bridge, ctx); // Refresh the list.
                        } else {
                            self.set_status("Failed to delete cluster", true);
                        }
                    }
                    Err(e) => {
                        self.set_status(&format!("Failed to delete cluster: {}", e), true);
                    }
                }
                ctx.mark_dirty();
                true
            }

            BridgeResponse::ClusterConnectionTested { request_id, result } => {
                if *request_id != self.request_id {
                    return false;
                }
                self.loading = false;
                match result {
                    Ok(conn_result) => {
                        self.connection_result = Some(ConnectionTestResult {
                            success: conn_result.success,
                            system_info: conn_result.system_info.clone(),
                            error: conn_result.error.clone(),
                        });
                    }
                    Err(e) => {
                        self.set_status(&format!("Connection test failed: {}", e), true);
                    }
                }
                ctx.mark_dirty();
                true
            }

            _ => false, // Not a cluster response — let other handlers try.
        }
    }
}

// ─── Private form-input helpers ────────────────────────────────────────────────

/// Map the currently focused form field to its backing `String`.
///
/// Returns `None` for non-text fields (`ClusterType`, which is toggled via Space).
/// Shared by the push/pop helpers so the field mapping lives in one place.
fn form_field_mut(state: &mut ClusterManagerState) -> Option<&mut String> {
    match state.focused_field {
        ClusterFormField::Name => Some(&mut state.form_name),
        ClusterFormField::Hostname => Some(&mut state.form_hostname),
        ClusterFormField::Port => Some(&mut state.form_port),
        ClusterFormField::Username => Some(&mut state.form_username),
        ClusterFormField::KeyFile => Some(&mut state.form_key_file),
        ClusterFormField::RemoteWorkdir => Some(&mut state.form_remote_workdir),
        ClusterFormField::QueueName => Some(&mut state.form_queue_name),
        ClusterFormField::Cry23Root => Some(&mut state.form_cry23_root),
        ClusterFormField::VaspRoot => Some(&mut state.form_vasp_root),
        ClusterFormField::MaxConcurrent => Some(&mut state.form_max_concurrent),
        ClusterFormField::ClusterType => None,
    }
}

/// Push a character into the currently focused form field.
///
/// Previously `handle_cluster_form_char` (main.rs ~1285-1319).
fn cluster_form_push_char(state: &mut ClusterManagerState, c: char, ctx: &mut HandlerCtx) {
    // Port and MaxConcurrent accept digits only and (unlike text fields) do not
    // clear the error banner on input.
    let digits_only = matches!(
        state.focused_field,
        ClusterFormField::Port | ClusterFormField::MaxConcurrent
    );
    if digits_only && !c.is_ascii_digit() {
        return;
    }
    let Some(field) = form_field_mut(state) else {
        return; // ClusterType is toggled via the Space key.
    };
    field.push(c);
    if !digits_only {
        state.error = None;
    }
    ctx.mark_dirty();
}

/// Remove the last character from the currently focused form field.
///
/// Previously `handle_cluster_form_backspace` (main.rs ~1322-1342).
fn cluster_form_pop_char(state: &mut ClusterManagerState, ctx: &mut HandlerCtx) {
    let Some(field) = form_field_mut(state) else {
        return;
    };
    field.pop();
    state.error = None;
    ctx.mark_dirty();
}

// ─── Unit tests ────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bridge::{BridgeResponse, BridgeService, JsonRpcRequest};
    use crate::models::{ClusterConfig, ClusterStatus, ClusterType};
    use anyhow::Result;
    use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
    use std::collections::VecDeque;
    use std::sync::{Arc, Mutex};

    // ── local recording mock ──────────────────────────────────────────────────

    struct MockBridge {
        requests: Arc<Mutex<Vec<String>>>,
        responses: Arc<Mutex<VecDeque<BridgeResponse>>>,
    }

    impl MockBridge {
        fn new() -> Self {
            Self {
                requests: Arc::new(Mutex::new(Vec::new())),
                responses: Arc::new(Mutex::new(VecDeque::new())),
            }
        }

        fn recorded(&self) -> Vec<String> {
            self.requests.lock().unwrap().clone()
        }
    }

    impl BridgeService for MockBridge {
        fn request_rpc(&self, rpc_request: JsonRpcRequest, request_id: usize) -> Result<()> {
            self.requests.lock().unwrap().push(format!(
                "Rpc(method={}, request_id={})",
                rpc_request.method, request_id
            ));
            Ok(())
        }

        fn poll_response(&self) -> Option<BridgeResponse> {
            self.responses.lock().unwrap().pop_front()
        }

        fn request_fetch_clusters(&self, request_id: usize) -> Result<()> {
            self.requests
                .lock()
                .unwrap()
                .push(format!("FetchClusters(request_id={})", request_id));
            Ok(())
        }

        fn request_create_cluster(
            &self,
            _config: &crate::models::ClusterConfig,
            request_id: usize,
        ) -> Result<()> {
            self.requests
                .lock()
                .unwrap()
                .push(format!("CreateCluster(request_id={})", request_id));
            Ok(())
        }

        fn request_update_cluster(
            &self,
            cluster_id: i32,
            _config: &crate::models::ClusterConfig,
            request_id: usize,
        ) -> Result<()> {
            self.requests.lock().unwrap().push(format!(
                "UpdateCluster(cluster_id={}, request_id={})",
                cluster_id, request_id
            ));
            Ok(())
        }

        fn request_delete_cluster(&self, cluster_id: i32, request_id: usize) -> Result<()> {
            self.requests.lock().unwrap().push(format!(
                "DeleteCluster(cluster_id={}, request_id={})",
                cluster_id, request_id
            ));
            Ok(())
        }

        fn request_test_cluster_connection(
            &self,
            cluster_id: i32,
            request_id: usize,
        ) -> Result<()> {
            self.requests.lock().unwrap().push(format!(
                "TestClusterConnection(cluster_id={}, request_id={})",
                cluster_id, request_id
            ));
            Ok(())
        }
    }

    // ── context helpers ───────────────────────────────────────────────────────

    fn make_ctx<'a>(
        id: &'a mut usize,
        err: &'a mut Option<String>,
        dirty: &'a mut bool,
    ) -> HandlerCtx<'a> {
        HandlerCtx {
            next_request_id: id,
            last_error: err,
            needs_redraw: dirty,
        }
    }

    fn key(code: KeyCode) -> KeyEvent {
        KeyEvent::new(code, KeyModifiers::NONE)
    }

    fn open_state() -> ClusterManagerState {
        let mut s = ClusterManagerState::default();
        s.open();
        s
    }

    fn make_cluster(id: i32, name: &str) -> ClusterConfig {
        ClusterConfig {
            id: Some(id),
            name: name.to_string(),
            cluster_type: ClusterType::Ssh,
            hostname: "host.example.com".to_string(),
            port: 22,
            username: "user".to_string(),
            key_file: None,
            remote_workdir: None,
            queue_name: None,
            max_concurrent: 4,
            cry23_root: None,
            vasp_root: None,
            setup_commands: Vec::new(),
            status: ClusterStatus::Active,
        }
    }

    // ── handle_key tests ──────────────────────────────────────────────────────

    /// Pressing 'a' in List mode switches to Add mode (no RPC).
    #[test]
    fn test_handle_key_list_a_enters_add_mode() {
        let bridge = MockBridge::new();
        let mut state = open_state();
        let mut id = 0usize;
        let mut err = None;
        let mut dirty = false;
        let mut ctx = make_ctx(&mut id, &mut err, &mut dirty);

        assert_eq!(state.mode, ClusterManagerMode::List);
        state.handle_key(key(KeyCode::Char('a')), &bridge, &mut ctx);

        assert_eq!(state.mode, ClusterManagerMode::Add);
        assert!(dirty, "mark_dirty should have been called");
        assert!(
            bridge.recorded().is_empty(),
            "no RPC expected for Add mode entry"
        );
    }

    /// Pressing Esc in Add mode returns to List mode without an RPC.
    #[test]
    fn test_handle_key_add_esc_cancels() {
        let bridge = MockBridge::new();
        let mut state = open_state();
        state.start_add();
        let mut id = 0usize;
        let mut err = None;
        let mut dirty = false;
        let mut ctx = make_ctx(&mut id, &mut err, &mut dirty);

        state.handle_key(key(KeyCode::Esc), &bridge, &mut ctx);

        assert_eq!(state.mode, ClusterManagerMode::List);
        assert!(bridge.recorded().is_empty());
    }

    /// Enter in Add mode with a valid form issues a CreateCluster RPC.
    #[test]
    fn test_handle_key_add_enter_creates_cluster_rpc() {
        let bridge = MockBridge::new();
        let mut state = open_state();
        state.start_add();
        // Fill in the minimum required fields.
        state.form_name = "my-cluster".to_string();
        state.form_hostname = "host.example.com".to_string();
        state.form_username = "alice".to_string();
        state.form_port = "22".to_string();
        state.form_max_concurrent = "4".to_string();

        let mut id = 0usize;
        let mut err = None;
        let mut dirty = false;
        let mut ctx = make_ctx(&mut id, &mut err, &mut dirty);

        state.handle_key(key(KeyCode::Enter), &bridge, &mut ctx);

        let recorded = bridge.recorded();
        assert_eq!(recorded.len(), 1);
        assert!(
            recorded[0].starts_with("CreateCluster("),
            "expected CreateCluster RPC, got: {}",
            recorded[0]
        );
        assert!(state.loading, "loading should be set after RPC dispatch");
    }

    // ── handle_response tests ─────────────────────────────────────────────────

    /// A `Clusters{Ok}` response with a matching request_id populates the list and
    /// clears the loading flag.
    #[test]
    fn test_handle_response_clusters_ok_populates_list() {
        let bridge = MockBridge::new();
        let mut state = open_state();
        let mut id = 0usize;
        let mut err = None;
        let mut dirty = false;

        // Simulate a pending fetch: give the state a request_id of 7.
        state.request_id = 7;
        state.loading = true;

        let resp = BridgeResponse::Clusters {
            request_id: 7,
            result: Ok(vec![make_cluster(1, "alpha"), make_cluster(2, "beta")]),
        };

        let mut ctx = make_ctx(&mut id, &mut err, &mut dirty);
        let claimed = state.handle_response(&resp, &bridge, &mut ctx);

        assert!(claimed, "cluster handler should claim Clusters response");
        assert!(!state.loading);
        assert_eq!(state.clusters.len(), 2);
        assert_eq!(state.selected_index, Some(0));
        assert!(dirty);
    }

    /// A `Clusters{Err}` response sets an error status.
    #[test]
    fn test_handle_response_clusters_err_sets_error() {
        let bridge = MockBridge::new();
        let mut state = open_state();
        state.request_id = 3;
        state.loading = true;
        let mut id = 0usize;
        let mut err = None;
        let mut dirty = false;

        let resp = BridgeResponse::Clusters {
            request_id: 3,
            result: Err(anyhow::anyhow!("backend down")),
        };

        let mut ctx = make_ctx(&mut id, &mut err, &mut dirty);
        let claimed = state.handle_response(&resp, &bridge, &mut ctx);

        assert!(claimed);
        assert!(!state.loading);
        assert!(state.error.is_some(), "error status should be set");
    }

    /// A `Clusters` response with a stale request_id is NOT claimed.
    #[test]
    fn test_handle_response_clusters_stale_not_claimed() {
        let bridge = MockBridge::new();
        let mut state = open_state();
        state.request_id = 5; // Expect 5.
        let mut id = 0usize;
        let mut err = None;
        let mut dirty = false;

        let resp = BridgeResponse::Clusters {
            request_id: 99, // Stale.
            result: Ok(vec![]),
        };

        let mut ctx = make_ctx(&mut id, &mut err, &mut dirty);
        let claimed = state.handle_response(&resp, &bridge, &mut ctx);

        assert!(!claimed, "stale response must not be claimed");
    }

    /// A `ClusterCreated{Ok}` response triggers a follow-up FetchClusters RPC.
    #[test]
    fn test_handle_response_cluster_created_triggers_refetch() {
        let bridge = MockBridge::new();
        let mut state = open_state();
        state.request_id = 1;
        state.loading = true;
        state.mode = ClusterManagerMode::Add;
        let mut id = 2usize; // Next RPC will get id=2.
        let mut err = None;
        let mut dirty = false;

        let resp = BridgeResponse::ClusterCreated {
            request_id: 1,
            result: Ok(make_cluster(42, "new-cluster")),
        };

        let mut ctx = make_ctx(&mut id, &mut err, &mut dirty);
        let claimed = state.handle_response(&resp, &bridge, &mut ctx);

        assert!(claimed);
        assert_eq!(
            state.mode,
            ClusterManagerMode::List,
            "cancel() should have reset mode"
        );
        let recorded = bridge.recorded();
        assert!(
            recorded.iter().any(|r| r.starts_with("FetchClusters(")),
            "expected a FetchClusters follow-up RPC, got: {:?}",
            recorded
        );
    }
}
