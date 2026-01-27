// =========================================================================
// Tests
// =========================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::{DftCode, JobDetails, JobStatus, MaterialResult, RunnerType};
    use anyhow::Result;
    use std::collections::VecDeque;
    use std::sync::{Arc, Mutex};

    // Mock Bridge Service
    struct MockBridgeService {
        requests: Arc<Mutex<Vec<String>>>,
        responses: Arc<Mutex<VecDeque<BridgeResponse>>>,
    }

    impl MockBridgeService {
        fn new() -> Self {
            Self {
                requests: Arc::new(Mutex::new(Vec::new())),
                responses: Arc::new(Mutex::new(VecDeque::new())),
            }
        }
    }

    impl BridgeService for MockBridgeService {
        fn request_fetch_jobs(&self, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!("FetchJobs(request_id={})", request_id));
            Ok(())
        }

        fn request_fetch_job_details(&self, pk: i32, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "FetchJobDetails(pk={}, request_id={})",
                pk, request_id
            ));
            Ok(())
        }

        fn request_submit_job(
            &self,
            _submission: &crate::models::JobSubmission,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!("SubmitJob(request_id={})", request_id));
            Ok(())
        }

        fn request_cancel_job(&self, pk: i32, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!("CancelJob(pk={}, request_id={})", pk, request_id));
            Ok(())
        }

        fn request_fetch_job_log(&self, pk: i32, tail_lines: i32, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "FetchJobLog(pk={}, tail_lines={}, request_id={})",
                pk, tail_lines, request_id
            ));
            Ok(())
        }

        fn request_search_materials(
            &self,
            formula: &str,
            limit: usize,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "SearchMaterials(formula={}, limit={}, request_id={})",
                formula, limit, request_id
            ));
            Ok(())
        }

        fn request_fetch_templates(&self, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!("FetchTemplates(request_id={})", request_id));
            Ok(())
        }

        fn request_render_template(
            &self,
            template_name: &str,
            params_json: &str,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "RenderTemplate(template_name={}, params_json={}, request_id={})",
                template_name, params_json, request_id
            ));
            Ok(())
        }

        fn request_generate_d12(
            &self,
            mp_id: &str,
            config_json: &str,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "GenerateD12(mp_id={}, config_json={}, request_id={})",
                mp_id, config_json, request_id
            ));
            Ok(())
        }

        fn request_fetch_slurm_queue(&self, cluster_id: i32, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "FetchSlurmQueue(cluster_id={}, request_id={})",
                cluster_id, request_id
            ));
            Ok(())
        }

        fn request_cancel_slurm_job(
            &self,
            cluster_id: i32,
            slurm_job_id: &str,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "CancelSlurmJob(cluster_id={}, slurm_job_id={}, request_id={})",
                cluster_id, slurm_job_id, request_id
            ));
            Ok(())
        }

        fn request_adopt_slurm_job(
            &self,
            cluster_id: i32,
            slurm_job_id: &str,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "AdoptSlurmJob(cluster_id={}, slurm_job_id={}, request_id={})",
                cluster_id, slurm_job_id, request_id
            ));
            Ok(())
        }

        fn request_sync_remote_jobs(&self, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!("SyncRemoteJobs(request_id={})", request_id));
            Ok(())
        }

        fn request_fetch_clusters(&self, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!("FetchClusters(request_id={})", request_id));
            Ok(())
        }

        fn request_create_cluster(
            &self,
            _config: &crate::models::ClusterConfig,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!("CreateCluster(request_id={})", request_id));
            Ok(())
        }

        fn request_update_cluster(
            &self,
            cluster_id: i32,
            _config: &crate::models::ClusterConfig,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "UpdateCluster(cluster_id={}, request_id={})",
                cluster_id, request_id
            ));
            Ok(())
        }

        fn request_delete_cluster(&self, cluster_id: i32, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
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
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "TestClusterConnection(cluster_id={}, request_id={})",
                cluster_id, request_id
            ));
            Ok(())
        }

        fn request_fetch_templates(&self, request_id: usize) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!("FetchTemplates(request_id={})", request_id));
            Ok(())
        }

        fn request_render_template(
            &self,
            template_name: &str,
            params_json: &str,
            request_id: usize,
        ) -> Result<()> {
            let mut reqs = self.requests.lock().unwrap();
            reqs.push(format!(
                "RenderTemplate(template_name={}, params_json={}, request_id={})",
                template_name, params_json, request_id
            ));
            Ok(())
        }

        fn poll_response(&self) -> Option<BridgeResponse> {
            let mut resps = self.responses.lock().unwrap();
            resps.pop_front()
        }
    }

    // Mock LSP Service
    struct MockLspService {
        calls: Arc<Mutex<Vec<String>>>,
    }

    impl MockLspService {
        fn new() -> Self {
            Self {
                calls: Arc::new(Mutex::new(Vec::new())),
            }
        }
    }

    impl LspService for MockLspService {
        fn send_initialized(&mut self) -> Result<()> {
            self.calls
                .lock()
                .unwrap()
                .push("send_initialized".to_string());
            Ok(())
        }

        fn did_open(&mut self, path: &str, _content: &str) -> Result<()> {
            self.calls
                .lock()
                .unwrap()
                .push(format!("did_open:{}", path));
            Ok(())
        }

        fn did_change(&mut self, path: &str, _version: i32, _content: &str) -> Result<()> {
            self.calls
                .lock()
                .unwrap()
                .push(format!("did_change:{}", path));
            Ok(())
        }

        fn did_close(&mut self, path: &str) -> Result<()> {
            self.calls
                .lock()
                .unwrap()
                .push(format!("did_close:{}", path));
        }
    }

    // Helper to create app with mocks
    fn create_test_app<'a>() -> App<'a> {
        let (_, lsp_rx) = mpsc::channel();

        let mut editor = TextArea::default();
        editor.set_line_number_style(
            ratatui::style::Style::default().fg(ratatui::style::Color::DarkGray),
        );

        App {
            should_quit: false,
            current_tab: AppTab::Jobs,
            last_error: None,
            last_error_time: None,
            needs_redraw: false,
            jobs_state: JobsState::default(),
            slurm_queue: Vec::new(),
            slurm_view_active: false,
            slurm_request_id: 0,
            slurm_selected: None,
            last_slurm_refresh: None,
            editor,
            editor_file_path: None,
            editor_file_uri: None,
            editor_dft_code: None,
            editor_version: 1,
            lsp_diagnostics: Vec::new(),
            current_job_details: None,
            results_scroll: 0,
            log_lines: Vec::new(),
            log_scroll: 0,
            log_job_pk: None,
            log_job_name: None,
            log_follow_mode: false,
            last_log_refresh: None,
            bridge: Box::new(MockBridgeService::new()), // Use mock bridge
            next_request_id: 0,
            pending_bridge_request: None,
            pending_request_id: None,
            pending_bridge_request_time: None,
            lsp_client: Some(Box::new(MockLspService::new())), // Use mock LSP
            lsp_receiver: lsp_rx,
            last_editor_change: None,
            pending_lsp_change: false,
            materials: MaterialsSearchState::default(),
            new_job: NewJobState::default(),
            cluster_manager: ClusterManagerState::default(),
            slurm_queue_state: SlurmQueueState::default(),
            last_slurm_cluster_id: None,
            vasp_input_state: crate::ui::VaspInputState::default(),
        }
    }

    // Test Helper for JobStatus
    fn test_job(pk: i32, name: &str) -> JobStatus {
        JobState {
            pk,
            uuid: format!("test-uuid-{}", pk),
            name: name.to_string(),
            state: JobState::Completed,
            runner_type: RunnerType::Local,
            progress_percent: None,
            wall_time_seconds: None,
            created_at: chrono::Utc::now(),
            error_snippet: None,
        }
    }

    // =========================================================================
    // General State Tests
    // =========================================================================

    #[test]
    fn test_app_tab_name() {
        assert_eq!(AppTab::Jobs.name(), "Jobs");
        assert_eq!(AppTab::Editor.name(), "Editor");
        assert_eq!(AppTab::Results.name(), "Results");
        assert_eq!(AppTab::Log.name(), "Log");
    }

    #[test]
    fn test_app_tab_all() {
        let tabs = AppTab::all();
        assert_eq!(tabs.len(), 4);
        assert_eq!(tabs[0], AppTab::Jobs);
        assert_eq!(tabs[1], AppTab::Editor);
        assert_eq!(tabs[2], AppTab::Results);
        assert_eq!(tabs[3], AppTab::Log);
    }

    // =========================================================================
    // Jobs State Tests
    // =========================================================================

    #[test]
    fn test_jobs_state_default() {
        let state = JobsState::default();
        assert!(state.jobs.is_empty());
        assert!(state.selected_index.is_none());
        assert!(state.last_refresh.is_none());
        assert!(state.changed_pks.is_empty());
        assert!(state.pending_cancel_pk.is_none());
        assert!(!state.pending_submit);
    }

    #[test]
    fn test_jobs_state_select_next_empty() {
        let mut state = JobsState::default();
        state.select_next();
        assert!(state.selected_index.is_none());
    }

    #[test]
    fn test_jobs_state_select_prev_empty() {
        let mut state = JobsState::default();
        state.select_prev();
        assert!(state.selected_index.is_none());
    }

    #[test]
    fn test_jobs_state_clear_pending_cancel() {
        let mut state = JobsState {
            pending_cancel_pk: Some(123),
            pending_cancel_time: Some(std::time::Instant::now()),
            ..Default::default()
        };

        state.clear_pending_cancel();
        assert!(state.pending_cancel_pk.is_none());
    }

    #[test]
    fn test_jobs_state_clear_pending_submit() {
        let mut state = JobsState {
            pending_submit: true,
            pending_submit_time: Some(std::time::Instant::now()),
            ..Default::default()
        };

        state.clear_pending_submit();
        assert!(!state.pending_submit);
    }

    // =========================================================================
    // Materials Search State Tests
    // =========================================================================

    #[test]
    fn test_materials_search_state_default() {
        let state = MaterialsSearchState::default();
        assert!(!state.active);
        assert!(state.results.is_empty());
        assert!(state.selected_for_import.is_none());
        assert!(!state.loading);
        assert!(!state.status_is_error);
    }

    fn test_material_res(id: &str, formula: &str) -> MaterialResult {
        MaterialResult {
            material_id: id.to_string(),
            formula: Some(formula.to_string()),
            formula_pretty: None,
            structure: "{}".to_string(),
            symmetry: None,
            formation_energy_per_atom: None,
            energy_above_hull: None,
            band_gap: None,
            is_metal: None,
            is_magnetic: None,
            ordering: None,
        }
    }

    #[test]
    fn test_materials_search_state_open() {
        let mut state = MaterialsSearchState::default();
        state.results.push(test_material_res("mp-1234", "MoS2"));
        state.loading = true;

        state.open();

        assert!(state.active);
        assert!(state.results.is_empty()); // Cleared on open
        assert!(!state.loading); // Reset on open
    }

    #[test]
    fn test_materials_search_state_close_increments_request_id() {
        let mut state = MaterialsSearchState::default();
        let initial_id = state.request_id;

        state.active = true;
        state.close();

        assert!(!state.active);
        assert_eq!(state.request_id, initial_id + 1);
    }

    #[test]
    fn test_materials_search_state_select_next() {
        let mut state = MaterialsSearchState::default();
        state.results = vec![
            test_material_res("mp-1", "A"),
            test_material_res("mp-2", "B"),
        ];
        state.table_state.select(Some(0));

        state.select_next();
        assert_eq!(state.table_state.selected(), Some(1));

        // Wrap around
        state.select_next();
        assert_eq!(state.table_state.selected(), Some(0));
    }

    #[test]
    fn test_materials_search_state_select_prev() {
        let mut state = MaterialsSearchState::default();
        state.results = vec![
            test_material_res("mp-1", "A"),
            test_material_res("mp-2", "B"),
        ];
        state.table_state.select(Some(0));

        // Wrap around
        state.select_prev();
        assert_eq!(state.table_state.selected(), Some(1));

        state.select_prev();
        assert_eq!(state.table_state.selected(), Some(0));
    }

    #[test]
    fn test_materials_search_state_set_status() {
        let mut state = MaterialsSearchState::default();

        state.set_status("Test error", true);
        assert!(state.status_is_error);

        state.set_status("Success", false);
        assert!(!state.status_is_error);
    }

    // =========================================================================
    // Action Tests
    // =========================================================================

    #[test]
    fn test_action_debug_format() {
        let action = Action::TabNext;
        let debug_str = format!("{:?}", action);
        assert_eq!(debug_str, "TabNext");
    }

    #[test]
    fn test_action_clone() {
        let action = Action::TabSet(AppTab::Editor);
        let cloned = action.clone();
        assert_eq!(action, cloned);
    }

    #[test]
    fn test_action_equality() {
        assert_eq!(Action::TabNext, Action::TabNext);
        assert_ne!(Action::TabNext, Action::TabPrev);
        assert_eq!(Action::TabSet(AppTab::Jobs), Action::TabSet(AppTab::Jobs));
        assert_ne!(Action::TabSet(AppTab::Jobs), Action::TabSet(AppTab::Editor));
    }

    // =========================================================================
    // Mock Service Tests
    // =========================================================================

    #[test]
    fn test_mock_bridge_service_captures_requests() {
        let mock = MockBridgeService::new();

        mock.request_fetch_jobs(1).unwrap();
        mock.request_fetch_job_details(42, 2).unwrap();

        let requests = mock.requests.lock().unwrap();
        assert_eq!(requests.len(), 2);
        assert_eq!(requests[0], "FetchJobs(request_id=1)");
        assert_eq!(requests[1], "FetchJobDetails(pk=42, request_id=2)");
    }

    #[test]
    fn test_mock_bridge_service_returns_responses() {
        let mock = MockBridgeService::new();

        // Initially empty
        assert!(mock.poll_response().is_none());

        // Add response
        {
            let mut resps = mock.responses.lock().unwrap();
            resps.push_back(BridgeResponse::Jobs {
                request_id: 1,
                result: Ok(Vec::new()),
            });
        }

        // Should pop one
        let resp = mock.poll_response();
        assert!(resp.is_some());
        if let Some(BridgeResponse::Jobs { request_id, .. }) = resp {
            assert_eq!(request_id, 1);
        } else {
            panic!("Wrong response type");
        }

        // Should be empty again
        assert!(mock.poll_response().is_none());
    }

    #[test]
    fn test_mock_lsp_service_captures_calls() {
        let mut mock = MockLspService::new();

        mock.send_initialized().unwrap();
        mock.did_open("test.d12", "content").unwrap();
        mock.did_change("test.d12", 2, "new content").unwrap();
        mock.did_close("test.d12").unwrap();

        let calls = mock.calls.lock().unwrap();
        assert_eq!(calls.len(), 4);
        assert_eq!(calls[0], "send_initialized");
        assert_eq!(calls[1], "did_open:test.d12");
        assert_eq!(calls[2], "did_change:test.d12");
        assert_eq!(calls[3], "did_close:test.d12");
    }

    // =========================================================================
    // App Logic Tests
    // =========================================================================

    #[test]
    fn test_tab_navigation_wraps_forward() {
        let mut app = create_test_app();
        assert_eq!(app.current_tab, AppTab::Jobs);

        app.next_tab();
        assert_eq!(app.current_tab, AppTab::Editor);

        app.next_tab();
        assert_eq!(app.current_tab, AppTab::Results);

        app.next_tab();
        assert_eq!(app.current_tab, AppTab::Log);

        app.next_tab();
        assert_eq!(app.current_tab, AppTab::Jobs);
    }

    #[test]
    fn test_tab_navigation_wraps_backward() {
        let mut app = create_test_app();
        assert_eq!(app.current_tab, AppTab::Jobs);

        app.prev_tab();
        assert_eq!(app.current_tab, AppTab::Log);

        app.prev_tab();
        assert_eq!(app.current_tab, AppTab::Results);

        app.prev_tab();
        assert_eq!(app.current_tab, AppTab::Editor);

        app.prev_tab();
        assert_eq!(app.current_tab, AppTab::Jobs);
    }

    #[test]
    fn test_tab_navigation_by_number() {
        let mut app = create_test_app();

        app.set_tab(AppTab::Jobs);
        assert_eq!(app.current_tab, AppTab::Jobs);

        app.set_tab(AppTab::Editor);
        assert_eq!(app.current_tab, AppTab::Editor);

        app.set_tab(AppTab::Results);
        assert_eq!(app.current_tab, AppTab::Results);

        app.set_tab(AppTab::Log);
        assert_eq!(app.current_tab, AppTab::Log);

        // Test setting same tab
        app.set_tab(AppTab::Log);
        assert_eq!(app.current_tab, AppTab::Log);

        app.set_tab(AppTab::Jobs);
        assert_eq!(app.current_tab, AppTab::Jobs);
    }

    #[test]
    fn test_set_tab_same_tab_does_not_mark_dirty() {
        let mut app = create_test_app();
        app.needs_redraw = false; // Reset initial dirty

        app.set_tab(AppTab::Jobs);
        assert!(!app.needs_redraw());

        app.set_tab(AppTab::Editor);
        assert!(app.needs_redraw());
    }

    #[test]
    fn test_needs_redraw_after_tab_change() {
        let mut app = create_test_app();
        app.take_needs_redraw(); // Clear initial

        app.next_tab();
        assert!(app.needs_redraw());

        app.take_needs_redraw();
        app.prev_tab();
        assert!(app.needs_redraw());
    }

    #[test]
    fn test_needs_redraw_after_job_selection_change() {
        let mut app = create_test_app();
        app.jobs_state.jobs = vec![test_job(1, "job1"), test_job(2, "job2")];
        app.jobs_state.selected_index = Some(0);
        app.take_needs_redraw();

        app.select_next_job();
        assert!(app.needs_redraw());

        app.take_needs_redraw();
        app.select_prev_job();
        assert!(app.needs_redraw());
    }

    #[test]
    fn test_update_action_tab_next() {
        let mut app = create_test_app();
        assert_eq!(app.current_tab, AppTab::Jobs);

        app.update(Action::TabNext);
        assert_eq!(app.current_tab, AppTab::Editor);
    }

    #[test]
    fn test_update_action_tab_prev() {
        let mut app = create_test_app();
        app.current_tab = AppTab::Editor;

        app.update(Action::TabPrev);
        assert_eq!(app.current_tab, AppTab::Jobs);
    }

    #[test]
    fn test_update_action_tab_set() {
        let mut app = create_test_app();

        app.update(Action::TabSet(AppTab::Log));
        assert_eq!(app.current_tab, AppTab::Log);
    }

    #[test]
    fn test_update_action_quit() {
        let mut app = create_test_app();
        assert!(!app.should_quit);

        app.update(Action::Quit);
        assert!(app.should_quit);
    }

    #[test]
    fn test_update_action_error_clear() {
        let mut app = create_test_app();
        app.set_error("Test error");
        assert!(app.last_error.is_some());

        app.update(Action::ErrorClear);
        assert!(app.last_error.is_none());
    }

    #[test]
    fn test_log_scroll_bounds() {
        let mut app = create_test_app();
        app.log_lines = vec!["line1".to_string(), "line2".to_string()];

        // Scroll down within bounds
        app.scroll_log_down(); // max is 0 (2 lines - 20 height clamped to 0)
        assert_eq!(app.log_scroll, 0);

        // Scroll up at top
        app.scroll_log_up();
        assert_eq!(app.log_scroll, 0);

        // Add more lines to allow scrolling
        for i in 0..30 {
            app.log_lines.push(format!("line{}", i + 3));
        }
        // Now 32 lines, max scroll = 12

        app.scroll_log_down();
        assert_eq!(app.log_scroll, 1);

        app.scroll_log_up();
        assert_eq!(app.log_scroll, 0);
    }

    #[test]
    fn test_log_scroll_top_and_bottom() {
        let mut app = create_test_app();
        for i in 0..30 {
            app.log_lines.push(format!("line{}", i));
        }
        // 30 lines, 20 visible -> max scroll 10

        app.scroll_log_bottom();
        assert_eq!(app.log_scroll, 10);

        app.scroll_log_top();
        assert_eq!(app.log_scroll, 0);

        // Test page scrolling
        app.scroll_log_page_down(); // +10
        assert_eq!(app.log_scroll, 10);

        app.scroll_log_page_up(); // -10
        assert_eq!(app.log_scroll, 0);
    }

    #[test]
    fn test_log_follow_mode_toggle() {
        let mut app = create_test_app();
        assert!(!app.log_follow_mode);

        app.toggle_log_follow();
        assert!(app.log_follow_mode);

        app.toggle_log_follow();
        assert!(!app.log_follow_mode);
    }

    #[test]
    fn test_results_scroll_bounds() {
        let mut app = create_test_app();
        // No details loaded
        app.scroll_results_down();
        assert_eq!(app.results_scroll, 0);

        // Add details
        app.current_job_details = Some(JobDetails {
            pk: 1,
            uuid: Some("uuid".to_string()),
            name: "job".to_string(),
            state: "completed".to_string(),
            dft_code: Some(DftCode::Crystal),
            input_file: Some("input.d12".to_string()),
            final_energy: None,
            bandgap_ev: None,
            wall_time: None,
            machine: None,
            input_content: None,
            stdout_tail: vec!["line".to_string(); 30], // 30 lines
            convergence_met: None,
            scf_cycles: None,
        });

        // Display line count will be header (assume 10 lines) + 30 log lines = 40
        // Scroll down
        app.scroll_results_down();
        assert_eq!(app.results_scroll, 1);

        app.scroll_results_up();
        assert_eq!(app.results_scroll, 0);
    }

    #[test]
    fn test_job_selection_bounds_upper() {
        let mut app = create_test_app();
        app.jobs_state.jobs = vec![test_job(1, "j1"), test_job(2, "j2"), test_job(3, "j3")];
        app.jobs_state.selected_index = Some(0);

        app.select_next_job();
        assert_eq!(app.jobs_state.selected_index, Some(1));

        app.select_next_job();
        assert_eq!(app.jobs_state.selected_index, Some(2));

        // Should not go past end
        app.select_next_job();
        assert_eq!(app.jobs_state.selected_index, Some(2));
    }

    #[test]
    fn test_job_selection_bounds_lower() {
        let mut app = create_test_app();
        app.jobs_state.jobs = vec![test_job(1, "j1"), test_job(2, "j2"), test_job(3, "j3")];
        app.jobs_state.selected_index = Some(2);

        app.select_prev_job();
        assert_eq!(app.jobs_state.selected_index, Some(1));

        app.select_prev_job();
        assert_eq!(app.jobs_state.selected_index, Some(0));

        // Should not go past 0
        app.select_prev_job();
        assert_eq!(app.jobs_state.selected_index, Some(0));
    }

    #[test]
    fn test_job_selection_empty_list_select_next() {
        let mut app = create_test_app();
        assert!(app.jobs_state.jobs.is_empty());
        assert!(app.jobs_state.selected_index.is_none());

        app.select_next_job();
        assert!(app.jobs_state.selected_index.is_none());
    }

    #[test]
    fn test_job_selection_empty_list_select_prev() {
        let mut app = create_test_app();
        assert!(app.jobs_state.jobs.is_empty());
        assert!(app.jobs_state.selected_index.is_none());

        app.select_prev_job();
        assert!(app.jobs_state.selected_index.is_none());
    }

    #[test]
    fn test_job_selection_first_and_last() {
        let mut app = create_test_app();
        // 5 jobs
        for i in 0..5 {
            app.jobs_state.jobs.push(test_job(i, &format!("j{}", i)));
        }
        app.jobs_state.selected_index = Some(2);

        app.select_first_job();
        assert_eq!(app.jobs_state.selected_index, Some(0));

        app.select_last_job();
        assert_eq!(app.jobs_state.selected_index, Some(4));
    }

    #[test]
    fn test_job_selection_first_on_empty_list() {
        let mut app = create_test_app();
        assert!(app.jobs_state.jobs.is_empty());

        app.select_first_job();
        assert!(app.jobs_state.selected_index.is_none());
    }

    #[test]
    fn test_job_selection_last_on_empty_list() {
        let mut app = create_test_app();
        assert!(app.jobs_state.jobs.is_empty());

        app.select_last_job();
        assert!(app.jobs_state.selected_index.is_none());
    }

    #[test]
    fn test_set_error_and_clear() {
        let mut app = create_test_app();
        assert!(app.last_error.is_none());

        app.set_error("Something went wrong");
        assert_eq!(app.last_error, Some("Something went wrong".to_string()));
        assert!(app.last_error_time.is_some());

        app.clear_error();
        assert!(app.last_error.is_none());
        assert!(app.last_error_time.is_none());
    }

    #[test]
    fn test_set_error_marks_dirty() {
        let mut app = create_test_app();
        app.take_needs_redraw();

        app.set_error("Error");
        assert!(app.needs_redraw());
    }

    #[test]
    fn test_clear_error_marks_dirty_only_if_error_exists() {
        let mut app = create_test_app();
        app.take_needs_redraw();

        // No error to clear
        app.clear_error();
        assert!(!app.needs_redraw());

        // Set error
        app.set_error("Error");
        app.take_needs_redraw();

        // Clear error
        app.clear_error();
        assert!(app.needs_redraw());
    }

    #[test]
    fn test_error_message_long_string() {
        let mut app = create_test_app();
        let long_message = "a".repeat(1000);
        app.set_error(long_message.clone());
        assert_eq!(app.last_error, Some(long_message));
    }

    #[test]
    fn test_error_message_special_characters() {
        let mut app = create_test_app();
        let special_msg = "Error: <script>alert('xss')</script> & other chars";
        app.set_error(special_msg);
        assert_eq!(app.last_error, Some(special_msg.to_string()));
    }

    #[test]
    fn test_last_slurm_cluster_remembered() {
        let mut app = create_test_app();
        assert!(app.last_slurm_cluster_id.is_none());

        app.last_slurm_cluster_id = Some(99);
        assert_eq!(app.last_slurm_cluster_id, Some(99));
    }

    #[test]
    fn test_last_slurm_cluster_cleared() {
        let mut app = create_test_app();
        app.last_slurm_cluster_id = Some(1);

        app.last_slurm_cluster_id = None;
        assert!(app.last_slurm_cluster_id.is_none());
    }

    #[test]
    fn test_mark_dirty_and_clear() {
        let mut app = create_test_app();
        app.needs_redraw = false;

        app.mark_dirty();
        assert!(app.needs_redraw());

        // Check without clearing
        assert!(app.needs_redraw());

        // Take and clear
        assert!(app.take_needs_redraw());
        assert!(!app.needs_redraw());
    }

    #[test]
    fn test_take_needs_redraw_returns_and_clears() {
        let mut app = create_test_app();
        app.mark_dirty();

        let dirty = app.take_needs_redraw();
        assert!(dirty);
        assert!(!app.needs_redraw());
    }

    #[test]
    fn test_selected_job_returns_correct_job() {
        let mut app = create_test_app();

        app.jobs_state.jobs = vec![
            test_job(1, "first"),
            test_job(2, "second"),
            test_job(3, "third"),
        ];
        app.jobs_state.selected_index = Some(1); // "second"

        let selected = app.selected_job();
        assert!(selected.is_some());
        assert_eq!(selected.unwrap().name, "second");
    }

    #[test]
    fn test_selected_job_returns_none_when_no_selection() {
        let mut app = create_test_app();

        app.jobs_state.jobs = vec![test_job(1, "job")];
        app.jobs_state.selected_index = None;

        assert!(app.selected_job().is_none());
    }

    #[test]
    fn test_selected_job_returns_none_when_empty_list() {
        let app = create_test_app();

        assert!(app.jobs_state.jobs.is_empty());
        assert!(app.selected_job().is_none());
    }

    #[test]
    fn test_materials_modal_open_close() {
        let mut app = create_test_app();

        // Initially closed
        assert!(!app.materials.active);

        // Open
        app.open_materials_modal();
        assert!(app.materials.active);
        assert!(app.needs_redraw());

        // Clear dirty and close
        app.take_needs_redraw();
        app.close_materials_modal();
        assert!(!app.materials.active);
        assert!(app.needs_redraw());
    }

    #[test]
    fn test_request_id_increments() {
        let mut app = create_test_app();

        let id1 = app.next_request_id();
        let id2 = app.next_request_id();
        let id3 = app.next_request_id();

        assert_eq!(id1, 0);
        assert_eq!(id2, 1);
        assert_eq!(id3, 2);
    }
}
