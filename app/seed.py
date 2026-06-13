"""Seed the master exercise catalog into the database.

Idempotent: running it twice has no effect on existing rows. Uses
``INSERT OR IGNORE`` so manual edits to rows are not clobbered.
"""
from __future__ import annotations

import json
from typing import Sequence, Tuple

from app.db import db_conn, init_schema

# (id_slug, display_name, muscle_group, form_cues)
EXERCISE_CATALOG: Sequence[Tuple[str, str, str, list[str]]] = [
    ("barbell-bench-press", "Barbell Bench Press", "Chest",
     ["Retract scapula, plant feet", "Bar to mid-chest", "Drive through lats, full lockout"]),
    ("incline-dumbbell-press", "Incline Dumbbell Press", "Chest",
     ["Bench at 30–45°", "Elbows ~45° to torso", "Press over upper chest, no clank at top"]),
    ("dumbbell-fly", "Dumbbell Fly", "Chest",
     ["Slight elbow bend, hold it", "Wide arc, stretch the chest", "Squeeze at the top"]),
    ("barbell-curl", "Barbell Curl", "Biceps",
     ["Elbows pinned to ribs", "No torso swing", "Full ROM, control the eccentric"]),
    ("dumbbell-hammer-curl", "Dumbbell Hammer Curl", "Biceps",
     ["Neutral grip", "Brachialis + forearm focus", "Slow negative"]),
    ("chest-dip", "Chest Dip", "Chest",
     ["Slight forward lean", "Elbows flare ~45°", "Depth to deep stretch, lock out"]),
    ("incline-dumbbell-curl", "Incline Dumbbell Curl", "Biceps",
     ["Bench at 60°", "Arms hang straight down", "Supinate as you curl"]),
    ("lat-pulldown", "Lat Pulldown", "Back",
     ["Wide grip, slight lean", "Pull bar to upper chest", "Lats initiate, no elbow yank"]),
    ("barbell-bent-over-row", "Barbell Bent-Over Row", "Back",
     ["Hinge ~45°", "Bar to lower sternum", "Squeeze shoulder blades, control descent"]),
    ("seated-cable-row", "Seated Cable Row", "Back",
     ["Tall chest, neutral spine", "Pull to lower ribs", "Pause, scapular retraction"]),
    ("triceps-pushdown", "Triceps Pushdown (Cable)", "Triceps",
     ["Elbows fixed at sides", "Wrists straight", "Full lockout, slow up"]),
    ("dumbbell-overhead-triceps-extension", "Overhead Dumbbell Triceps Extension", "Triceps",
     ["Elbows narrow + vertical", "Deep stretch behind head", "No flaring"]),
    ("one-arm-dumbbell-row", "One-Arm Dumbbell Row", "Back",
     ["Brace on bench", "Pull to hip, not chest", "Squeeze, control"]),
    ("barbell-full-squat", "Barbell Back Squat", "Legs",
     ["Brace core, neutral spine", "Knees track over toes", "Below parallel, drive through mid-foot"]),
    ("romanian-deadlift", "Romanian Deadlift", "Legs",
     ["Soft knees, hinge at hips", "Bar slides down thighs", "Feel hamstring stretch, snap hips"]),
    ("leg-press", "Leg Press", "Legs",
     ["Feet shoulder-width on platform", "Knees to ~90°, don't lock", "Full controlled ROM"]),
    ("lying-leg-curl", "Lying Leg Curl", "Legs",
     ["Pad above heels", "Curl with hamstrings, no hip lift", "Slow eccentric"]),
    ("standing-calf-raise", "Standing Calf Raise", "Calves",
     ["Full stretch at bottom", "Drive up onto toes", "Pause, squeeze, slow drop"]),
    ("leg-extension", "Leg Extension", "Legs",
     ["Back pinned to seat", "Knee tracks the cam", "Slight pause at top"]),
    ("dumbbell-walking-lunge", "Dumbbell Walking Lunge", "Legs",
     ["Long stride, torso upright", "Back knee kisses floor", "Drive through front heel"]),
    ("barbell-shoulder-press", "Barbell Overhead Press", "Shoulders",
     ["Bar on front delts", "Brace glutes + core", "Press straight up, head through at lockout"]),
    ("dumbbell-lateral-raise", "Dumbbell Lateral Raise", "Shoulders",
     ["Slight elbow bend", "Lead with elbows, not hands", "Stop at shoulder height"]),
    ("dumbbell-reverse-fly", "Dumbbell Reverse Fly", "Shoulders",
     ["Hinge forward, chest down", "Pinch shoulder blades", "Slight elbow bend, no swing"]),
    ("dumbbell-front-raise", "Dumbbell Front Raise", "Shoulders",
     ["Neutral or pronated grip", "Raise to shoulder height", "Slow eccentric"]),
    ("dumbbell-shrug", "Dumbbell Shrug", "Shoulders",
     ["Straight up, not rolling", "Pause, squeeze upper traps", "Avoid head jutting"]),
    ("dumbbell-shoulder-press", "Dumbbell Shoulder Press", "Shoulders",
     ["Seated, back supported", "Wrists stacked over elbows", "Press, slight in-tilt at top"]),
]


def seed_exercises() -> int:
    """Insert the master catalog. Returns count of newly inserted rows."""
    init_schema()
    inserted = 0
    with db_conn() as conn:
        for slug, name, muscle, cues in EXERCISE_CATALOG:
            cur = conn.execute(
                """INSERT OR IGNORE INTO exercises (id, name, muscle_group, form_cues, media_slug)
                   VALUES (?, ?, ?, ?, ?)""",
                (slug, name, muscle, json.dumps(cues), slug),
            )
            inserted += cur.rowcount or 0
    return inserted


def main() -> None:
    n = seed_exercises()
    print(f"[seed] schema ready. inserted {n} new exercises (catalog total: {len(EXERCISE_CATALOG)})")


if __name__ == "__main__":
    main()
