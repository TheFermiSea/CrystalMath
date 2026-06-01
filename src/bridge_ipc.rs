//! IPC-backed implementation of [`BridgeService`].
//!
//! This is the keystone of the PyO3 -> IPC cutover (ADR-006). It mirrors the
//! shape of the PyO3 `BridgeHandle` (a dedicated worker thread fronted by two
//! bounded channels) but, instead of embedding Python via PyO3, it talks to the
//! standalone `crystalmath-server` over a Unix domain socket using
//! [`crate::ipc::IpcClient`].
//!
//! The transport-agnostic plumbing is reused verbatim:
//! - [`BridgeRequest`] / [`BridgeResponse`] are the same channel payloads.
//! - [`crate::bridge::route_rpc_response`] maps a raw JSON-RPC response back to
//!   the typed `BridgeResponse` the UI expects (including per-method error
//!   handling such as `NOT_FOUND` -> `Ok(None)`).
//! - Every typed `request_*` helper comes from the `BridgeService` default
//!   methods; only [`request_rpc`](BridgeService::request_rpc) and
//!   [`poll_response`](BridgeService::poll_response) are implemented here.
//!
//! The worker owns one [`IpcClient`] and processes requests strictly serially
//! (one outstanding request per connection), which matches the client's
//! sequential request/response contract.

use std::path::PathBuf;
use std::sync::mpsc::{self, Receiver, SyncSender, TrySendError};
use std::thread;
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use tracing::{error, info, warn};

use crate::bridge::{
    route_rpc_response, BridgeRequest, BridgeResponse, BridgeService, JsonRpcRequest, CHANNEL_BOUND,
};
use crate::ipc::{IpcClient, IpcError};

/// Handle to the IPC bridge worker thread.
///
/// Drop-in replacement for `BridgeHandle` behind the `BridgeService` trait
/// object that `App` holds. Non-blocking: requests are queued via a bounded
/// channel and responses are polled from another, so the 60fps UI thread never
/// blocks on the socket.
pub struct IpcBridgeHandle {
    request_tx: SyncSender<BridgeRequest>,
    response_rx: Receiver<BridgeResponse>,
    worker_handle: Option<thread::JoinHandle<()>>,
}

impl IpcBridgeHandle {
    /// Spawn the IPC bridge worker, connecting to (and auto-starting) the
    /// `crystalmath-server` at `socket_path`.
    ///
    /// The actual connection is established lazily on the first request (and
    /// re-established if the server is restarted), so spawning never blocks.
    pub fn spawn(socket_path: PathBuf) -> Result<Self> {
        let (request_tx, request_rx) = mpsc::sync_channel::<BridgeRequest>(CHANNEL_BOUND);
        let (response_tx, response_rx) = mpsc::sync_channel::<BridgeResponse>(CHANNEL_BOUND);

        let worker_handle = thread::Builder::new()
            .name("ipc-bridge".to_string())
            .spawn(move || {
                let rt = match tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                {
                    Ok(rt) => rt,
                    Err(e) => {
                        error!("IPC bridge: failed to build tokio runtime: {}", e);
                        return;
                    }
                };
                rt.block_on(ipc_worker_loop(socket_path, request_rx, response_tx));
            })
            .context("Failed to spawn IPC bridge worker thread")?;

        Ok(Self {
            request_tx,
            response_rx,
            worker_handle: Some(worker_handle),
        })
    }

    /// Non-blocking send to the worker (mirrors `BridgeHandle::try_send_request`).
    fn try_send_request(&self, request: BridgeRequest) -> Result<()> {
        match self.request_tx.try_send(request) {
            Ok(()) => Ok(()),
            Err(TrySendError::Full(_)) => Err(anyhow!("Backend busy - try again in a moment")),
            Err(TrySendError::Disconnected(_)) => Err(anyhow!("IPC bridge worker disconnected")),
        }
    }
}

impl BridgeService for IpcBridgeHandle {
    fn request_rpc(&self, rpc_request: JsonRpcRequest, request_id: usize) -> Result<()> {
        self.try_send_request(BridgeRequest::Rpc {
            rpc_request,
            request_id,
        })
    }

    fn poll_response(&self) -> Option<BridgeResponse> {
        self.response_rx.try_recv().ok()
    }
}

impl Drop for IpcBridgeHandle {
    fn drop(&mut self) {
        // Signal the worker to exit; ignore errors (it may already be gone).
        let _ = self.request_tx.send(BridgeRequest::Shutdown);

        if let Some(handle) = self.worker_handle.take() {
            const QUICK_CHECK_INTERVAL: Duration = Duration::from_millis(10);
            const MAX_QUICK_CHECKS: u32 = 10; // ~100ms total
            for _ in 0..MAX_QUICK_CHECKS {
                if handle.is_finished() {
                    if let Err(e) = handle.join() {
                        warn!("IPC bridge worker thread panicked during shutdown: {:?}", e);
                    } else {
                        tracing::debug!("IPC bridge worker thread shut down gracefully");
                    }
                    return;
                }
                thread::sleep(QUICK_CHECK_INTERVAL);
            }
            // Detach: a blocked socket read should not stall app shutdown.
            tracing::debug!("IPC bridge worker still running after ~100ms - detaching");
        }
    }
}

/// Returns true for errors that indicate the connection itself is gone (so a
/// single reconnect is worth attempting). Timeouts/protocol errors are surfaced
/// to the user instead of silently retried.
fn is_connection_error(err: &IpcError) -> bool {
    matches!(err, IpcError::ConnectionFailed(_) | IpcError::Io(_))
}

/// The worker loop: owns the `IpcClient`, drains the request channel, and routes
/// each response back. Runs inside a current-thread tokio runtime on a dedicated
/// OS thread (so the blocking `recv()` between requests is harmless).
async fn ipc_worker_loop(
    socket_path: PathBuf,
    request_rx: Receiver<BridgeRequest>,
    response_tx: SyncSender<BridgeResponse>,
) {
    let mut client: Option<IpcClient> = None;

    while let Ok(request) = request_rx.recv() {
        let (rpc_request, request_id) = match request {
            BridgeRequest::Shutdown => break,
            BridgeRequest::Rpc {
                rpc_request,
                request_id,
            } => (rpc_request, request_id),
        };
        let method = rpc_request.method.clone();

        // Lazily (re)connect. connect_or_start auto-spawns the server if needed.
        if client.is_none() {
            match IpcClient::connect_or_start(&socket_path).await {
                Ok(c) => {
                    info!("IPC bridge connected to crystalmath-server");
                    client = Some(c);
                }
                Err(e) => {
                    // Surface a per-request error so the UI's pending state clears
                    // promptly instead of waiting for the 30s timeout.
                    let msg = anyhow!(
                        "Backend unavailable: {} (is crystalmath-server installed? \
                         `uv pip install -e python/`)",
                        e
                    );
                    if response_tx
                        .send(route_rpc_response(&method, request_id, Err(msg)))
                        .is_err()
                    {
                        break;
                    }
                    continue;
                }
            }
        }

        // Safe: just ensured Some above.
        let mut result = client.as_mut().unwrap().call_rpc(&rpc_request).await;

        // On mid-session connection loss, drop the client and try ONE reconnect.
        if matches!(&result, Err(e) if is_connection_error(e)) {
            warn!(
                "IPC bridge: connection lost on '{}'; attempting one reconnect",
                method
            );
            client = None;
            if let Ok(mut fresh) = IpcClient::connect_or_start(&socket_path).await {
                result = fresh.call_rpc(&rpc_request).await;
                client = Some(fresh);
            }
            // If reconnect failed, `result` keeps the original connection error.
        }

        let rpc_result = result.map_err(anyhow::Error::new);
        if response_tx
            .send(route_rpc_response(&method, request_id, rpc_result))
            .is_err()
        {
            break; // UI dropped the receiver
        }
    }

    info!("IPC bridge worker exiting");
}
