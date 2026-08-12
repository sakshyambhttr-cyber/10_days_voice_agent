"""
Database module for BolBuddy Voice Agent persistent memory storage.

Provides SQLite persistence for user identity, language preferences, learning-related facts,
and interaction timestamps. Designed to survive agent restarts, backend restarts, and new sessions.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("agent.db")

# Default database directory and file location inside backend
DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DEFAULT_DB_PATH = os.path.join(DEFAULT_DATA_DIR, "bolbuddy_memory.db")


def get_db_path(override_path: Optional[str] = None) -> str:
    """Get the active database file path."""
    if override_path:
        return override_path
    return os.getenv("BOLBUDDY_DB_PATH", DEFAULT_DB_PATH)


def _get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Create and return an SQLite database connection with row factory configured."""
    active_path = get_db_path(db_path)
    os.makedirs(os.path.dirname(os.path.abspath(active_path)), exist_ok=True)
    conn = sqlite3.connect(active_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[str] = None) -> bool:
    """
    Initialize the SQLite database schema if it doesn't already exist.
    Creates the data directory and user_memory table safely.
    """
    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_memory (
                    user_id TEXT PRIMARY KEY,
                    name TEXT,
                    language_preference TEXT,
                    facts TEXT DEFAULT '{}',
                    phone_number TEXT,
                    preferred_practice_time TEXT,
                    last_interaction TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # Migration check for existing user_memory tables
            cursor.execute("PRAGMA table_info(user_memory)")
            existing_cols = [row["name"] for row in cursor.fetchall()]
            if "phone_number" not in existing_cols:
                cursor.execute("ALTER TABLE user_memory ADD COLUMN phone_number TEXT")
            if "preferred_practice_time" not in existing_cols:
                cursor.execute(
                    "ALTER TABLE user_memory ADD COLUMN preferred_practice_time TEXT"
                )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_calls (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    phone_number TEXT NOT NULL,
                    scheduled_time TEXT NOT NULL,
                    status TEXT DEFAULT 'SCHEDULED',
                    attempt_count INTEGER DEFAULT 0,
                    last_attempt_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_schedules (
                    user_id TEXT PRIMARY KEY,
                    phone_number TEXT NOT NULL,
                    practice_topic TEXT NOT NULL DEFAULT 'Spoken English Practice',
                    preferred_time TEXT NOT NULL,
                    timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    next_call_at TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS escalations (
                    reference_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    who_needs_help TEXT NOT NULL,
                    reason_type TEXT NOT NULL,
                    issue_summary TEXT NOT NULL,
                    checked_by_agent TEXT,
                    urgency TEXT NOT NULL DEFAULT 'medium',
                    preferred_language TEXT DEFAULT 'English',
                    preferred_contact TEXT DEFAULT 'phone',
                    status TEXT DEFAULT 'OPEN',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS call_analytics (
                    call_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    duration INTEGER DEFAULT 0,
                    channel TEXT DEFAULT 'browser',
                    outcome TEXT DEFAULT 'in_progress',
                    failure_reason TEXT,
                    completed_activities INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # Migration: Automatically update calls with duration >= 30s to success
            cursor.execute(
                """
                UPDATE call_analytics
                SET outcome = 'success',
                    failure_reason = NULL,
                    completed_activities = CASE WHEN completed_activities = 0 THEN 1 ELSE completed_activities END
                WHERE outcome = 'failed' AND duration >= 30
                """
            )
            conn.commit()
            logger.info(
                f"Database schema initialized successfully at {get_db_path(db_path)}"
            )
            return True
    except sqlite3.Error as e:
        logger.error(f"Failed to initialize SQLite database: {e}", exc_info=True)
        return False


def get_user(user_id: str, db_path: Optional[str] = None) -> Optional[dict[str, Any]]:
    """
    Retrieve a user's persistent memory record by user_id.

    Returns:
        dict containing user_id, name, language_preference, facts (as dict), last_interaction, etc.,
        or None if user does not exist or if a database error occurs.
    """
    if not user_id:
        logger.warning("get_user called with empty user_id")
        return None

    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT user_id, name, language_preference, facts, phone_number, preferred_practice_time, last_interaction, created_at, updated_at
                FROM user_memory
                WHERE user_id = ?
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            user_dict = dict(row)
            # Deserialize facts JSON safely
            try:
                user_dict["facts"] = (
                    json.loads(user_dict["facts"]) if user_dict["facts"] else {}
                )
            except (json.JSONDecodeError, TypeError) as parse_err:
                logger.warning(
                    f"Failed to parse facts JSON for user {user_id}: {parse_err}"
                )
                user_dict["facts"] = {}

            return user_dict
    except sqlite3.Error as e:
        logger.error(
            f"Database error in get_user for user_id '{user_id}': {e}", exc_info=True
        )
        return None


def create_or_update_user(
    user_id: str,
    name: Optional[str] = None,
    language_preference: Optional[str] = None,
    facts: Optional[dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """
    Create a new user memory record or update an existing record.
    Preserves existing fields if None is passed for optional arguments.

    Args:
        user_id: Unique persistent identifier for the user.
        name: User's preferred name.
        language_preference: Preferred language mode (e.g. "English + Hindi").
        facts: Structured dictionary of learning facts (e.g. level, goals, topics_practiced).
        db_path: Optional database path override.

    Returns:
        Updated user record as a dict, or None on failure.
    """
    if not user_id:
        logger.warning("create_or_update_user called with empty user_id")
        return None

    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        # Fetch existing record to merge fields cleanly if partial updates are passed
        existing_user = get_user(user_id, db_path=db_path)

        final_name = (
            name
            if name is not None
            else (existing_user.get("name") if existing_user else None)
        )
        final_lang = (
            language_preference
            if language_preference is not None
            else (existing_user.get("language_preference") if existing_user else None)
        )

        # Merge facts if existing facts exist
        if existing_user and existing_user.get("facts"):
            merged_facts = dict(existing_user["facts"])
            if facts:
                merged_facts.update(facts)
        else:
            merged_facts = facts or {}

        facts_json = json.dumps(merged_facts)

        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO user_memory (user_id, name, language_preference, facts, last_interaction, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    name = COALESCE(excluded.name, user_memory.name),
                    language_preference = COALESCE(excluded.language_preference, user_memory.language_preference),
                    facts = excluded.facts,
                    last_interaction = excluded.last_interaction,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    final_name,
                    final_lang,
                    facts_json,
                    now_iso,
                    now_iso,
                    now_iso,
                ),
            )
            conn.commit()

        logger.info(f"User record created/updated successfully for user_id: {user_id}")
        return get_user(user_id, db_path=db_path)
    except sqlite3.Error as e:
        logger.error(
            f"Database error in create_or_update_user for '{user_id}': {e}",
            exc_info=True,
        )
        return None


def update_last_interaction(user_id: str, db_path: Optional[str] = None) -> bool:
    """
    Update the last_interaction and updated_at timestamps for a given user_id.

    Returns:
        True if record was updated, False if user does not exist or database error occurred.
    """
    if not user_id:
        return False

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE user_memory
                SET last_interaction = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (now_iso, now_iso, user_id),
            )
            conn.commit()
            if cursor.rowcount > 0:
                logger.info(f"Updated last_interaction for user_id: {user_id}")
                return True
            else:
                logger.warning(
                    f"update_last_interaction: user_id '{user_id}' not found"
                )
                return False
    except sqlite3.Error as e:
        logger.error(
            f"Database error in update_last_interaction for '{user_id}': {e}",
            exc_info=True,
        )
        return False


def delete_user(user_id: str, db_path: Optional[str] = None) -> bool:
    """
    Delete a user record by user_id (useful for test cleanup or future forget functionality).

    Returns:
        True if deleted, False otherwise.
    """
    if not user_id:
        return False

    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_memory WHERE user_id = ?", (user_id,))
            conn.commit()
            return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(
            f"Database error in delete_user for '{user_id}': {e}", exc_info=True
        )
        return False


def get_or_create_user(
    user_id: str,
    name: Optional[str] = None,
    language_preference: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """
    Retrieve existing user record or create a new initial record if user does not exist yet.
    """
    existing = get_user(user_id, db_path=db_path)
    if existing:
        update_last_interaction(user_id, db_path=db_path)
        return get_user(user_id, db_path=db_path)

    return create_or_update_user(
        user_id=user_id,
        name=name,
        language_preference=language_preference,
        facts={
            "current_level": "beginner",
            "learning_goal": "everyday conversation",
            "topics_practiced": [],
            "recurring_challenges": [],
        },
        db_path=db_path,
    )


def record_learning_progress(
    user_id: str,
    current_level: Optional[str] = None,
    learning_goal: Optional[str] = None,
    topics_practiced: Optional[list[str]] = None,
    recurring_challenges: Optional[list[str]] = None,
    db_path: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """
    Helper to update a user's learning facts while preserving existing topics and challenges.
    Appends new unique topics and challenges to existing lists.
    """
    user = get_user(user_id, db_path=db_path)
    if not user:
        user = create_or_update_user(user_id=user_id, db_path=db_path)
        if not user:
            return None

    existing_facts = user.get("facts") or {}

    new_facts = dict(existing_facts)

    if current_level is not None:
        new_facts["current_level"] = current_level

    if learning_goal is not None:
        new_facts["learning_goal"] = learning_goal

    # Deduplicate and append topics
    if topics_practiced:
        current_topics = list(new_facts.get("topics_practiced", []))
        for topic in topics_practiced:
            if topic and topic not in current_topics:
                current_topics.append(topic)
        new_facts["topics_practiced"] = current_topics

    # Deduplicate and append challenges
    if recurring_challenges:
        current_challenges = list(new_facts.get("recurring_challenges", []))
        for challenge in recurring_challenges:
            if challenge and challenge not in current_challenges:
                current_challenges.append(challenge)
        new_facts["recurring_challenges"] = current_challenges

    return create_or_update_user(user_id=user_id, facts=new_facts, db_path=db_path)


def save_learner_outbound_preferences(
    user_id: str,
    phone_number: str,
    preferred_practice_time: str,
    name: Optional[str] = None,
    db_path: Optional[str] = None,
) -> bool:
    """Save user's phone number and preferred practice time in persistent database."""
    if not user_id or not phone_number:
        return False
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO user_memory (user_id, name, phone_number, preferred_practice_time, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    name = COALESCE(excluded.name, user_memory.name),
                    phone_number = excluded.phone_number,
                    preferred_practice_time = excluded.preferred_practice_time,
                    updated_at = excluded.updated_at
                """,
                (user_id, name, phone_number, preferred_practice_time, now_iso),
            )
            conn.commit()
            return True
    except sqlite3.Error as e:
        logger.error(
            f"Failed to save learner outbound preferences for '{user_id}': {e}",
            exc_info=True,
        )
        return False


def create_scheduled_call(
    user_id: str,
    phone_number: str,
    scheduled_time: str,
    db_path: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Create a new scheduled practice call entry."""
    import uuid

    if not user_id or not phone_number:
        return None
    call_id = f"call_{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO scheduled_calls (id, user_id, phone_number, scheduled_time, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'SCHEDULED', ?, ?)
                """,
                (call_id, user_id, phone_number, scheduled_time, now_iso, now_iso),
            )
            conn.commit()
        return {
            "id": call_id,
            "user_id": user_id,
            "phone_number": phone_number,
            "scheduled_time": scheduled_time,
            "status": "SCHEDULED",
            "attempt_count": 0,
            "created_at": now_iso,
        }
    except sqlite3.Error as e:
        logger.error(
            f"Failed to create scheduled call for '{user_id}': {e}", exc_info=True
        )
        return None


def get_scheduled_calls(
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    db_path: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Retrieve scheduled call records filtered by user_id or status."""
    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            query = "SELECT id, user_id, phone_number, scheduled_time, status, attempt_count, last_attempt_at, created_at, updated_at FROM scheduled_calls"
            params = []
            conditions = []
            if user_id:
                conditions.append("user_id = ?")
                params.append(user_id)
            if status:
                conditions.append("status = ?")
                params.append(status)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY created_at DESC"
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"Failed to get scheduled calls: {e}", exc_info=True)
        return []


def update_call_status(
    call_id: str,
    status: str,
    increment_attempt: bool = False,
    db_path: Optional[str] = None,
) -> bool:
    """Update scheduled call status and optionally increment attempt count."""
    if not call_id:
        return False
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            if increment_attempt:
                cursor.execute(
                    """
                    UPDATE scheduled_calls
                    SET status = ?, attempt_count = attempt_count + 1, last_attempt_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status, now_iso, now_iso, call_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE scheduled_calls
                    SET status = ?, last_attempt_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status, now_iso, now_iso, call_id),
                )
            conn.commit()
            return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(
            f"Failed to update call status for '{call_id}': {e}", exc_info=True
        )
        return False


def save_escalation(
    reference_id: str,
    user_id: str,
    who_needs_help: str,
    reason_type: str,
    issue_summary: str,
    checked_by_agent: str = "",
    urgency: str = "medium",
    preferred_language: str = "English",
    preferred_contact: str = "phone",
    status: str = "OPEN",
    db_path: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """
    Save or update a human escalation request in SQLite database.
    """
    if not reference_id or not user_id:
        return None
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO escalations (
                    reference_id, user_id, who_needs_help, reason_type, issue_summary,
                    checked_by_agent, urgency, preferred_language, preferred_contact, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(reference_id) DO UPDATE SET
                    issue_summary = excluded.issue_summary,
                    checked_by_agent = excluded.checked_by_agent,
                    urgency = excluded.urgency,
                    preferred_language = excluded.preferred_language,
                    preferred_contact = excluded.preferred_contact,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    reference_id,
                    user_id,
                    who_needs_help,
                    reason_type,
                    issue_summary,
                    checked_by_agent,
                    urgency,
                    preferred_language,
                    preferred_contact,
                    status,
                    now_iso,
                    now_iso,
                ),
            )
            conn.commit()
        return {
            "reference_id": reference_id,
            "user_id": user_id,
            "who_needs_help": who_needs_help,
            "reason_type": reason_type,
            "issue_summary": issue_summary,
            "checked_by_agent": checked_by_agent,
            "urgency": urgency,
            "preferred_language": preferred_language,
            "preferred_contact": preferred_contact,
            "status": status,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
    except sqlite3.Error as e:
        logger.error(f"Failed to save escalation '{reference_id}': {e}", exc_info=True)
        return None


def get_open_escalation_by_user(
    user_id: str,
    reason_type: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Find existing open escalation request for user to prevent duplicate tickets."""
    if not user_id:
        return None
    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM escalations WHERE user_id = ? AND status = 'OPEN'"
            params = [user_id]
            if reason_type:
                query += " AND reason_type = ?"
                params.append(reason_type)
            query += " ORDER BY created_at DESC LIMIT 1"
            cursor.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else None
    except sqlite3.Error as e:
        logger.error(
            f"Failed to get open escalation for '{user_id}': {e}", exc_info=True
        )
        return None


def get_escalations(
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    db_path: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Retrieve all escalation tickets filtered by user_id or status."""
    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM escalations"
            conditions = []
            params = []
            if user_id:
                conditions.append("user_id = ?")
                params.append(user_id)
            if status:
                conditions.append("status = ?")
                params.append(status)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY created_at DESC"
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"Failed to fetch escalations: {e}", exc_info=True)
        return []


def update_escalation_status(
    reference_id: str,
    status: str,
    db_path: Optional[str] = None,
) -> bool:
    """Update escalation ticket status (OPEN, IN_PROGRESS, RESOLVED)."""
    if not reference_id:
        return False
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE escalations SET status = ?, updated_at = ? WHERE reference_id = ?",
                (status, now_iso, reference_id),
            )
            conn.commit()
            return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(
            f"Failed to update escalation status for '{reference_id}': {e}",
            exc_info=True,
        )
        return False


# ============================================================================
# Day 8 — Call Analytics Database Utilities
# ============================================================================


def record_call_start(
    call_id: str,
    user_id: Optional[str] = None,
    channel: str = "browser",
    db_path: Optional[str] = None,
) -> dict[str, Any]:
    """Record a new call session starting in 'in_progress' state."""
    if not call_id:
        return {"success": False, "error": "call_id is required"}

    started_at = datetime.now(timezone.utc).isoformat()
    chan = "sip" if channel and "sip" in channel.lower() else "browser"

    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO call_analytics (call_id, user_id, started_at, channel, outcome)
                VALUES (?, ?, ?, ?, 'in_progress')
                ON CONFLICT(call_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    started_at = excluded.started_at,
                    channel = excluded.channel
                """,
                (call_id, user_id, started_at, chan),
            )
            conn.commit()
            return {
                "success": True,
                "call_id": call_id,
                "user_id": user_id,
                "started_at": started_at,
                "channel": chan,
                "outcome": "in_progress",
            }
    except sqlite3.Error as e:
        logger.error(f"Failed to record call start for '{call_id}': {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def mark_call_outcome(
    call_id: str,
    outcome: str = "success",
    failure_reason: Optional[str] = None,
    completed_activities_inc: int = 0,
    db_path: Optional[str] = None,
) -> dict[str, Any]:
    """
    Mark or update call outcome and increment completed learning activities.
    outcome should be 'success' or 'failed'.
    """
    if not call_id:
        return {"success": False, "error": "call_id is required"}

    valid_outcome = "success" if outcome == "success" else "failed"

    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT call_id, completed_activities
                FROM call_analytics
                WHERE call_id = ? OR user_id = ?
                ORDER BY started_at DESC LIMIT 1
                """,
                (call_id, call_id),
            )
            row = cursor.fetchone()
            target_call_id = row["call_id"] if row else call_id
            current_act = row["completed_activities"] if row else 0
            new_act = max(0, current_act + completed_activities_inc)

            cursor.execute(
                """
                UPDATE call_analytics
                SET outcome = ?,
                    failure_reason = ?,
                    completed_activities = ?
                WHERE call_id = ?
                """,
                (valid_outcome, failure_reason, new_act, target_call_id),
            )
            conn.commit()
            return {
                "success": True,
                "call_id": target_call_id,
                "outcome": valid_outcome,
                "failure_reason": failure_reason,
                "completed_activities": new_act,
            }
    except sqlite3.Error as e:
        logger.error(f"Failed to mark call outcome for '{call_id}': {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def finalize_call(
    call_id: str,
    default_outcome: str = "failed",
    default_reason: str = "incomplete_exercise",
    db_path: Optional[str] = None,
) -> dict[str, Any]:
    """
    Finalize call session when session ends:
    Calculates duration, sets ended_at, and ensures outcome is set ('success' or 'failed').
    If call outcome was already marked 'success' or duration >= 30s or activities > 0, marks 'success'.
    Otherwise sets outcome to default_outcome (e.g. 'failed') with default_reason.
    """
    if not call_id:
        return {"success": False, "error": "call_id is required"}

    ended_at_dt = datetime.now(timezone.utc)
    ended_at = ended_at_dt.isoformat()

    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT call_id, started_at, outcome, failure_reason, completed_activities
                FROM call_analytics
                WHERE call_id = ? OR user_id = ?
                ORDER BY started_at DESC LIMIT 1
                """,
                (call_id, call_id),
            )
            row = cursor.fetchone()

            if not row:
                # If call record was somehow not created at start, create it now as finalized
                duration = 0
                final_outcome = default_outcome
                reason = default_reason if final_outcome == "failed" else None
                new_act = 1 if final_outcome == "success" else 0
                cursor.execute(
                    """
                    INSERT INTO call_analytics (call_id, started_at, ended_at, duration, outcome, failure_reason, completed_activities)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (call_id, ended_at, ended_at, duration, final_outcome, reason, new_act),
                )
                target_call_id = call_id
            else:
                target_call_id = row["call_id"]
                current_outcome = row["outcome"]
                current_reason = row["failure_reason"]
                current_act = row["completed_activities"] or 0
                started_at_str = row["started_at"]

                # Calculate duration in integer seconds
                duration = 0
                if started_at_str:
                    try:
                        started_at_dt = datetime.fromisoformat(started_at_str)
                        duration = max(0, int((ended_at_dt - started_at_dt).total_seconds()))
                    except Exception:
                        duration = 0

                # Mark success if explicitly marked success OR duration >= 30s OR activities > 0
                if current_outcome == "success" or duration >= 30 or current_act > 0:
                    final_outcome = "success"
                    reason = None
                    new_act = max(1, current_act)
                else:
                    final_outcome = default_outcome
                    reason = None if final_outcome == "success" else (current_reason or default_reason or "incomplete_exercise")
                    new_act = current_act

                cursor.execute(
                    """
                    UPDATE call_analytics
                    SET ended_at = ?,
                        duration = ?,
                        outcome = ?,
                        failure_reason = ?,
                        completed_activities = ?
                    WHERE call_id = ?
                    """,
                    (ended_at, duration, final_outcome, reason, new_act, target_call_id),
                )

            conn.commit()
            return {
                "success": True,
                "call_id": target_call_id,
                "ended_at": ended_at,
                "duration": duration,
                "outcome": final_outcome,
                "failure_reason": reason,
            }
    except sqlite3.Error as e:
        logger.error(f"Failed to finalize call for '{call_id}': {e}", exc_info=True)
        return {"success": False, "error": str(e)}


def get_analytics_summary(db_path: Optional[str] = None) -> dict[str, Any]:
    """
    Fetch overall call analytics metrics from SQLite.
    Only counts finalized calls ('success' or 'failed').
    """
    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()

            # Total finalized calls
            cursor.execute(
                "SELECT COUNT(*) as total FROM call_analytics WHERE outcome IN ('success', 'failed')"
            )
            total_calls = cursor.fetchone()["total"]

            # Successful calls count
            cursor.execute(
                "SELECT COUNT(*) as successful FROM call_analytics WHERE outcome = 'success'"
            )
            successful_calls = cursor.fetchone()["successful"]

            # Failed calls count
            cursor.execute(
                "SELECT COUNT(*) as failed FROM call_analytics WHERE outcome = 'failed'"
            )
            failed_calls = cursor.fetchone()["failed"]

            # Completed learning activities sum
            cursor.execute(
                "SELECT SUM(completed_activities) as total_act FROM call_analytics WHERE outcome IN ('success', 'failed')"
            )
            act_row = cursor.fetchone()
            completed_activities = (act_row["total_act"] or 0) if act_row else 0

            # Success rate calculation
            success_rate = (
                round((successful_calls / total_calls) * 100.0, 1)
                if total_calls > 0
                else 0.0
            )

            # Failure reasons breakdown
            cursor.execute(
                """
                SELECT failure_reason, COUNT(*) as count
                FROM call_analytics
                WHERE outcome = 'failed' AND failure_reason IS NOT NULL
                GROUP BY failure_reason
                """
            )
            failure_reasons = {
                row["failure_reason"]: row["count"] for row in cursor.fetchall()
            }

            return {
                "success": True,
                "total_calls": total_calls,
                "successful_calls": successful_calls,
                "failed_calls": failed_calls,
                "success_rate": success_rate,
                "completed_activities": completed_activities,
                "failure_reasons": failure_reasons,
            }
    except sqlite3.Error as e:
        logger.error(f"Failed to fetch analytics summary: {e}", exc_info=True)
        return {
            "success": False,
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "success_rate": 0.0,
            "completed_activities": 0,
            "failure_reasons": {},
        }


def _format_duration(seconds: int) -> str:
    """Format duration in seconds to 'Xm Ys' or 'Xs'."""
    if seconds <= 0:
        return "0s"
    mins = seconds // 60
    secs = seconds % 60
    if mins > 0:
        return f"{mins}m {secs:02d}s"
    return f"{secs}s"


def get_recent_calls(
    limit: int = 10, db_path: Optional[str] = None
) -> list[dict[str, Any]]:
    """
    Fetch recent finalized call sessions for display in dashboard.
    Excludes sensitive transcript or caller details.
    """
    try:
        with _get_connection(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT call_id, user_id, started_at, ended_at, duration, channel, outcome, failure_reason, completed_activities
                FROM call_analytics
                WHERE outcome IN ('success', 'failed')
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            res = []
            for r in rows:
                dur_sec = r["duration"] or 0
                res.append(
                    {
                        "call_id": r["call_id"],
                        "user_id": r["user_id"],
                        "started_at": r["started_at"],
                        "ended_at": r["ended_at"],
                        "duration": dur_sec,
                        "duration_formatted": _format_duration(dur_sec),
                        "channel": (
                            "SIP"
                            if r["channel"] and "sip" in r["channel"].lower()
                            else "Browser"
                        ),
                        "outcome": (
                            "Successful" if r["outcome"] == "success" else "Failed"
                        ),
                        "failure_reason": r["failure_reason"],
                        "completed_activities": r["completed_activities"] or 0,
                    }
                )
            return res
    except sqlite3.Error as e:
        logger.error(f"Failed to fetch recent calls: {e}", exc_info=True)
        return []

