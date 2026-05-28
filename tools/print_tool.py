"""
Print Tools — Print documents to the default physical printer.
Renders markdown as formatted output (not raw symbols).
"""

import os
import sys
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app_platform.jobs import (
    create_print_job as _create_print_job,
    create_recipe_print_job as _create_recipe_print_job,
    get_job as _get_job,
    cancel_job as _cancel_job,
)


def print_doc(
    doc_id: str,
    requested_by: str,
    copies: str = "1",
) -> str:
    """Print a document to the default physical printer.

    The document's markdown content is rendered as formatted output (headings,
    bold, tables, etc.) — not raw markdown symbols. Printing runs as a
    background job and you'll be notified when it's sent to the printer.

    Args:
        doc_id: The document ID to print (e.g. "d-abc12345").
        requested_by: Who is requesting the print (e.g. "alice").
        copies: Number of copies to print, 1-10. Defaults to "1".

    Returns:
        Confirmation with job ID.

    Ack: Sending document to printer...
    """
    try:
        if not doc_id or not doc_id.strip():
            return "Error: doc_id is required."
        if not requested_by or not requested_by.strip():
            return "Error: requested_by is required."

        doc_id = doc_id.strip()
        if not doc_id.startswith("d-"):
            return f"Error: '{doc_id}' doesn't look like a document ID (expected d-*)."

        try:
            n = int(copies)
        except (ValueError, TypeError):
            n = 1

        job = _create_print_job(
            doc_id=doc_id,
            requested_by=requested_by.strip(),
            copies=n,
        )

        copies_msg = f"{n} {'copy' if n == 1 else 'copies'}"
        return (
            f"Print job queued ({job['id']})\n"
            f"  Document: {doc_id}\n"
            f"  Copies: {copies_msg}\n"
            f"  Status: queued (will start within ~30 seconds)\n"
            f"I'll notify you when it's been sent to the printer."
        )

    except Exception as e:
        return f"Error in print_doc: {str(e)}"


def print_recipe(
    recipe_id: str,
    requested_by: str,
    copies: str = "1",
) -> str:
    """Print a recipe to the default physical printer.

    The recipe is rendered as a nicely formatted page with title,
    ingredients list, numbered instructions, and meta info —
    ready to pin on the fridge or take to the kitchen.

    Args:
        recipe_id: The recipe ID to print (e.g. "re-abc12345").
        requested_by: Who is requesting the print (e.g. "alice").
        copies: Number of copies to print, 1-10. Defaults to "1".

    Returns:
        Confirmation with job ID.

    Ack: Sending recipe to printer...
    """
    try:
        if not recipe_id or not recipe_id.strip():
            return "Error: recipe_id is required."
        if not requested_by or not requested_by.strip():
            return "Error: requested_by is required."

        recipe_id = recipe_id.strip()
        if not recipe_id.startswith("re-"):
            return f"Error: '{recipe_id}' doesn't look like a recipe ID (expected re-*)."

        try:
            n = int(copies)
        except (ValueError, TypeError):
            n = 1

        job = _create_recipe_print_job(
            recipe_id=recipe_id,
            requested_by=requested_by.strip(),
            copies=n,
        )

        copies_msg = f"{n} {'copy' if n == 1 else 'copies'}"
        return (
            f"Print job queued ({job['id']})\n"
            f"  Recipe: {recipe_id}\n"
            f"  Copies: {copies_msg}\n"
            f"  Status: queued (will start within ~30 seconds)\n"
            f"I'll notify you when it's been sent to the printer."
        )

    except Exception as e:
        return f"Error in print_recipe: {str(e)}"
