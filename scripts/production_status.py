"""Read-only production dashboard derived from project artifacts and immutable job state."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def latest(project, patterns):
    matches = []
    for pattern in patterns:
        matches.extend(path for path in project.glob(pattern) if path.is_file())
    return max(matches, key=lambda path: (path.stat().st_mtime_ns, path.as_posix())) if matches else None


def gate_summary(project, name):
    path = latest(project, [f"planning/{name}-gate*.json", f"planning/{name}*.gate.json"])
    if not path:
        return {"present": False, "ready": False, "path": None, "errors": []}
    report = read_json(path)
    return {"present": True, "ready": report.get("ready") is True,
            "path": str(path), "errors": report.get("errors", [])}


def job_summaries(project):
    provider_jobs = []
    provider_root = project / "jobs"
    if provider_root.is_dir():
        for path in sorted(provider_root.glob("*/job.json")):
            value = read_json(path)
            provider_jobs.append({"id": value.get("id", path.parent.name), "provider": value.get("request", {}).get("provider"),
                                  "state": value.get("state", "unknown"), "approved": bool(value.get("approval")),
                                  "path": str(path.parent)})
    render_jobs = []
    render_root = project / "render-jobs"
    if render_root.is_dir():
        for path in sorted(render_root.glob("[0-9a-f]*/job.json")):
            dispatch = path.parent / "dispatch.json"
            state = read_json(dispatch).get("status", "prepared") if dispatch.is_file() else "prepared"
            render_jobs.append({"id": path.parent.name, "state": state, "path": str(path.parent)})
    return provider_jobs, render_jobs


def review_summaries(project):
    reviews = []
    for path in sorted((project / "reviews").glob("**/review-report.json")) if (project / "reviews").is_dir() else []:
        report = read_json(path)
        reviews.append({"shot_id": report.get("shot_id"), "disposition": report.get("disposition", "unknown"),
                        "path": str(path)})
    return reviews


def delivery_summary(project):
    path = latest(project, ["delivery-qa*.json", "**/delivery-qa*.json"])
    if not path:
        return {"present": False, "technical_pass": False, "path": None, "errors": []}
    report = read_json(path)
    return {"present": True, "technical_pass": report.get("technical_pass") is True,
            "path": str(path), "errors": report.get("errors", [])}


def inspect(project_path):
    project = Path(project_path).resolve()
    production_path = project / "production.json"
    if not project.is_dir() or not production_path.is_file():
        raise ValueError("Project must be an initialized production directory containing production.json")
    production = read_json(production_path)
    if production.get("version") != 1:
        raise ValueError("Unsupported production.json version")

    direction = gate_summary(project, "direction")
    styleframes = gate_summary(project, "styleframes")
    rough_cut = gate_summary(project, "rough-cut")
    delivery = delivery_summary(project)
    provider_jobs, render_jobs = job_summaries(project)
    reviews = review_summaries(project)
    artifacts = {
        "idea": (project / "idea.txt").is_file(),
        "interview": (project / "interview.json").is_file(),
        "brief": (project / "brief.md").is_file(),
        "direction": (project / "direction.md").is_file(),
        "storyboard": (project / "storyboard.md").is_file(),
        "direction_contract": (project / "planning/direction-v1.json").is_file(),
        "shot_contract": (project / "planning/shots-v1.json").is_file(),
    }

    blockers = []
    for label in ("idea", "interview"):
        if not artifacts[label]:
            blockers.append(f"missing required intake artifact: {label}")
    if direction["present"] and not direction["ready"]:
        blockers.extend(f"direction gate: {error}" for error in direction["errors"])
    if styleframes["present"] and not styleframes["ready"]:
        blockers.extend(f"styleframes gate: {error}" for error in styleframes["errors"])
    if rough_cut["present"] and not rough_cut["ready"]:
        blockers.extend(f"rough-cut gate: {error}" for error in rough_cut["errors"])
    for job in provider_jobs:
        if job["state"] in {"submitting", "unknown", "received_needs_review"}:
            blockers.append(f"provider job {job['id']} requires reconciliation ({job['state']})")
    for job in render_jobs:
        if job["state"] in {"failed", "unknown"}:
            blockers.append(f"render job {job['id']} requires diagnosis ({job['state']})")
    for review in reviews:
        if review["disposition"] != "passed":
            blockers.append(f"shot {review['shot_id']} review disposition is {review['disposition']}")
    if delivery["present"] and not delivery["technical_pass"]:
        blockers.extend(f"delivery QA: {error}" for error in delivery["errors"] or ["technical_pass is false"])
    if delivery["technical_pass"] and not reviews:
        blockers.append("delivery exists but no finalized shot review evidence was found")

    if not direction["ready"]:
        phase = "direction"
        next_actions = ["complete brief.md, direction.md and planning/direction-v1.json", "run the direction gate"]
    elif not styleframes["ready"]:
        phase = "styleframes"
        next_actions = ["complete storyboard.md and planning/shots-v1.json", "review styleframes and run the styleframes gate"]
    elif not rough_cut["ready"]:
        phase = "production"
        next_actions = ["produce or select the contracted shot sources", "mark selected sources and run the rough-cut gate"]
    elif not delivery["present"]:
        phase = "finishing"
        next_actions = ["assemble the selected cut", "run delivery_qa.py on the encoded output"]
    elif not delivery["technical_pass"] or not reviews or any(item["disposition"] != "passed" for item in reviews):
        phase = "review"
        next_actions = ["watch complete motion and sound", "finalize timecoded shot reviews and repair delivery QA failures"]
    else:
        phase = "complete"
        next_actions = ["retain the approved master and receipts", "perform only the explicitly authorized delivery action"]

    return {
        "schema_version": 1,
        "project": str(project),
        "phase": phase,
        "production_status_field": production.get("status"),
        "artifacts": artifacts,
        "gates": {"direction": direction, "styleframes": styleframes, "rough_cut": rough_cut},
        "jobs": {"provider": provider_jobs, "render": render_jobs},
        "reviews": reviews,
        "delivery": delivery,
        "external_actions_authorized_by_initialization": production.get("external_actions_authorized_by_initialization", []),
        "blockers": blockers,
        "next_actions": next_actions,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(inspect(args.project), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
