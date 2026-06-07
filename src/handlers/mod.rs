//! Per-domain Handler trait and HandlerCtx.
//!
//! This module defines the `Handler` trait — the per-domain behaviour seam — and
//! the `HandlerCtx` helper that carries cross-cutting App state a handler legitimately
//! needs without requiring a borrow of the full `App` struct.
//!
//! Each domain (cluster manager, SLURM queue, …) implements `Handler` so that its
//! input dispatch, RPC-response handling, and orchestration logic live in one place
//! and are directly unit-testable against a mock `BridgeService`.
//!
//! **Render deferral (crystalmath-3y4.3):** Render is intentionally omitted from the
//! trait for this pilot. The render fns in `src/ui/cluster_manager.rs` still take
//! `&App` and will be decoupled in a follow-up task.

use crate::bridge::{BridgeResponse, BridgeService};
use crossterm::event::KeyEvent;

/// Borrowed, disjoint subset of `App` fields that a `Handler` may use.
///
/// Using split-borrow-friendly `&mut` refs avoids handing the whole `App` to the
/// handler while still letting it drive the dirty flag, the error display, and the
/// monotonically-increasing request ID counter.
pub struct HandlerCtx<'a> {
    /// Backing storage for the per-domain request-ID counter (App::next_request_id).
    pub next_request_id: &'a mut usize,
    /// Last non-fatal error string displayed in the status bar (App::last_error).
    // Used by set_error; will be read by additional handlers as the trait rolls out.
    #[allow(dead_code)]
    pub last_error: &'a mut Option<String>,
    /// Dirty flag — set when the UI must be redrawn (App::needs_redraw).
    pub needs_redraw: &'a mut bool,
}

impl HandlerCtx<'_> {
    /// Allocate the next unique request ID (wrapping add, same semantics as App).
    pub fn next_request_id(&mut self) -> usize {
        let id = *self.next_request_id;
        *self.next_request_id = id.wrapping_add(1);
        id
    }

    /// Set a non-fatal error and mark the UI dirty.
    // Will be called by handlers that surface errors to the global status bar.
    // Unused in the pilot but part of the trait contract for follow-on adapters.
    #[allow(dead_code)]
    pub fn set_error(&mut self, m: impl Into<String>) {
        *self.last_error = Some(m.into());
        *self.needs_redraw = true;
    }

    /// Mark the UI as needing a redraw.
    pub fn mark_dirty(&mut self) {
        *self.needs_redraw = true;
    }
}

/// A per-domain deep module that owns input dispatch and RPC-response handling.
///
/// `is_active` is queried by the input ladder to determine whether this handler
/// should be offered key events.  `handle_key` and `handle_response` are the two
/// hot paths; both return a boolean indicating whether they consumed the event/response
/// so the caller can implement "first match wins" dispatch.
pub trait Handler {
    /// Whether this domain's modal/panel is currently active.
    // Used by the registry dispatch planned for crystalmath-3y4.3.
    #[allow(dead_code)]
    fn is_active(&self) -> bool;

    /// Process a key event.  Returns `true` if the key was consumed.
    fn handle_key(
        &mut self,
        key: KeyEvent,
        bridge: &dyn BridgeService,
        ctx: &mut HandlerCtx,
    ) -> bool;

    /// Process a bridge response.  Returns `true` if this handler claimed it.
    fn handle_response(
        &mut self,
        resp: &BridgeResponse,
        bridge: &dyn BridgeService,
        ctx: &mut HandlerCtx,
    ) -> bool;
}

pub mod cluster;
