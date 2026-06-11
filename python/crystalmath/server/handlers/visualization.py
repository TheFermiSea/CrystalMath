import os
import pathlib
import re
import xml.etree.ElementTree as ET
from typing import Any

import matplotlib

matplotlib.use("Agg")  # Thread-safe non-interactive backend
import matplotlib.pyplot as plt


def extract_convergence_data(code: str, work_dir: pathlib.Path) -> list[dict[str, Any]]:
    """
    Parses raw quantum chemistry out files line-by-line to reconstruct
    the optimization trajectory arrays.
    """
    steps = []

    if code == "crystal23":
        out_file = work_dir / "crystal.out"
        if out_file.exists():
            with open(out_file) as f:
                cycle = 0
                for line in f:
                    # Capture optimization step indicators
                    if "OPTIMIZATION CYCLE" in line or "CYCLE" in line and "ETOT" in line:
                        match = re.search(r"(?:CYCLE|CYCLE\s+)\s*(\d+)", line)
                        if match:
                            cycle = int(match.group(1))
                    if "TOTAL ENERGY(AU)" in line or "E(AU)" in line:
                        tokens = line.split()
                        try:
                            # Pluck the float value out of the text string
                            val = float(tokens[-1]) if tokens[-1] != "AU" else float(tokens[-2])
                            steps.append(
                                {"step": cycle, "energy": val * 27.211386}
                            )  # Convert Hartree to eV
                        except (ValueError, IndexError):
                            pass

    elif code == "vasp":
        vasprun = work_dir / "vasprun.xml"
        if vasprun.exists():
            try:
                tree = ET.parse(vasprun)
                root = tree.getroot()
                # Trace all ionic steps down the XML calculation tree
                for idx, calc in enumerate(root.findall(".//calculation")):
                    energy_node = calc.find(".//energy/i[@name='e_wo_entrp']")
                    if energy_node is not None and energy_node.text:
                        steps.append({"step": idx + 1, "energy": float(energy_node.text.strip())})
            except Exception:
                # Fallback to structural line scanning if XML is truncated mid-run
                outcar = work_dir / "OUTCAR"
                if outcar.exists():
                    with open(outcar) as f:
                        idx = 1
                        for line in f:
                            if "free energy    TOTEN" in line:
                                try:
                                    steps.append({"step": idx, "energy": float(line.split()[-2])})
                                    idx += 1
                                except (ValueError, IndexError):
                                    pass

    elif code == "qe":
        out_file = work_dir / "qe.out"
        if out_file.exists():
            with open(out_file) as f:
                idx = 1
                for line in f:
                    if "!" in line and "total energy" in line:
                        try:
                            # Pluck Quantum Espresso Rydberg energy and convert to eV
                            val = float(line.split()[4])
                            steps.append({"step": idx, "energy": val * 13.605693})
                            idx += 1
                        except (ValueError, IndexError):
                            pass
    return steps


def handle_get_visualization_data(job_id: int, db: Any) -> dict[str, Any]:
    job = db.get_job(job_id)
    if not job:
        return {"status": "error", "message": f"Job {job_id} not found"}

    work_dir = pathlib.Path(job.work_dir)
    code = job.dft_code.lower()

    try:
        steps = extract_convergence_data(code, work_dir)
        return {
            "status": "success",
            "data": {"job_id": job_id, "code": code, "convergence_steps": steps},
        }
    except Exception as e:
        return {"status": "error", "message": f"Parsing failure: {str(e)}"}


def handle_generate_plot_image(
    job_id: int, plot_type: str, cache_dir: str, db: Any
) -> dict[str, Any]:
    """
    Generates pristine standalone matplotlib figures, saving them
    directly to a shared workspace cache area for the Rust TUI to render.
    """
    data_res = handle_get_visualization_data(job_id, db)
    if data_res["status"] == "error":
        return data_res

    steps_data = data_res["data"]["convergence_steps"]
    if not steps_data:
        return {
            "status": "error",
            "message": "No numerical vector metrics resolved for this calculation log.",
        }

    os.makedirs(cache_dir, exist_ok=True)
    target_path = os.path.join(cache_dir, f"job_{job_id}_{plot_type}.png")

    # Configure custom professional styling handles
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.set_facecolor("#1e1e2e")  # Slate dark canvas background match
    fig.patch.set_facecolor("#1e1e2e")

    if plot_type == "convergence":
        x = [s["step"] for s in steps_data]
        y = [s["energy"] for s in steps_data]

        ax.plot(
            x,
            y,
            color="#89b4fa",
            marker="o",
            markersize=4,
            linestyle="-",
            linewidth=1.5,
            label="Total Energy",
        )
        ax.set_xlabel("Optimization Step", color="#cdd6f4", fontsize=10)
        ax.set_ylabel("Energy (eV)", color="#cdd6f4", fontsize=10)
        ax.set_title(
            f"Job #{job_id} ({data_res['data']['code'].upper()}) Trajectory Tracking",
            color="#cdd6f4",
            fontsize=12,
        )
        ax.grid(True, linestyle="--", alpha=0.15, color="#block")

    ax.tick_params(colors="#cdd6f4", labelsize=9)
    for spine in ax.spines.values():
        spine.set_color("#313244")

    plt.tight_layout()
    plt.savefig(target_path, dpi=180, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)

    return {"status": "success", "image_path": target_path}
