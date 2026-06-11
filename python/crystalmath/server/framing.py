import json
import struct


class IPCFrameEncoder:
    """
    High-performance frame encoder matching the Rust layout.
    Prefixes payloads with binary headers to prevent text scanning over sockets.
    """

    MAGIC = b"CMAT"
    HEADER_FORMAT = "!4sIH"  # Magic, Payload Len, Msg Type

    @classmethod
    def encode_frame(
        cls, job_id: int, code_engine: str, stream_channel: str, payload: str, msg_type: int = 1
    ) -> bytes:
        frame_dict = {
            "job_id": job_id,
            "code_engine": code_engine,
            "stream_channel": stream_channel,
            "payload": payload,
        }
        serialized = json.dumps(frame_dict, separators=(",", ":")).encode("utf-8")
        header = struct.pack(cls.HEADER_FORMAT, cls.MAGIC, len(serialized), msg_type)
        return header + serialized
