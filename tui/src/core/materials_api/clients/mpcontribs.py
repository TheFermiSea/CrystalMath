"""Async wrapper for MPContribs API.

MPContribs is a platform for user contributions to Materials Project, allowing
researchers to share computed and experimental data associated with MP materials.

Documentation: https://docs.materialsproject.org/services/mpcontribs
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, TYPE_CHECKING

from ..settings import MaterialsSettings
from ..models import ContributionRecord
from ..errors import (
    AuthenticationError,
    MaterialsAPIError,
    NetworkError,
    RateLimitError,
    StructureNotFoundError,
)

if TYPE_CHECKING:
    from mpcontribs.client import Client as MpContribsClientSync

logger = logging.getLogger(__name__)


class MpContribsClient:
    """Async client for MPContribs user contributions API.

    Wraps the synchronous mpcontribs Client with asyncio.to_thread.

    Example:
        client = MpContribsClient()
        projects = await client.list_projects()
        contributions = await client.get_contributions("carrier_transport", formula="GaAs")
    """

    SOURCE = "mpcontribs"

    def __init__(self, api_key: str | None = None, host: str | None = None) -> None:
        """Initialize client.

        Args:
            api_key: MPContribs API key (falls back to MPCONTRIBS_API_KEY or MP_API_KEY)
            host: API host (default: contribs-api.materialsproject.org)
        """
        settings = MaterialsSettings.get_instance()

        self._api_key = api_key or settings.mpcontribs_api_key
        self._host = host or settings.mpcontribs_api_host

        # Lazy-loaded sync client
        self._client: MpContribsClientSync | None = None

    def _get_sync_client(self) -> MpContribsClientSync:
        """Get or create the synchronous MPContribs client.

        Returns:
            Configured mpcontribs Client instance

        Raises:
            AuthenticationError: If no API key is configured
            NetworkError: If client initialization fails
        """
        if self._client is not None:
            return self._client

        if not self._api_key:
            raise AuthenticationError(
                source=self.SOURCE,
                message=(
                    "No API key configured for MPContribs. "
                    "Set MPCONTRIBS_API_KEY or MP_API_KEY environment variable. "
                    "Get your key at: https://materialsproject.org/api"
                ),
            )

        try:
            from mpcontribs.client import Client

            self._client = Client(apikey=self._api_key, host=self._host)
            logger.debug("MPContribs client initialized for host: %s", self._host)
            return self._client
        except ImportError as exc:
            raise MaterialsAPIError(
                message=(
                    "mpcontribs-client package not installed. "
                    "Install with: pip install mpcontribs-client"
                ),
                source=self.SOURCE,
            ) from exc
        except Exception as exc:
            raise NetworkError(source=self.SOURCE, original_error=exc) from exc

    def _handle_exception(self, exc: Exception, context: str = "") -> None:
        """Convert mpcontribs exceptions to our error types.

        Args:
            exc: Exception from mpcontribs client
            context: Additional context for error message

        Raises:
            AuthenticationError: For 401/403 errors
            RateLimitError: For 429 errors
            NetworkError: For connection issues
            MaterialsAPIError: For other API errors
        """
        exc_str = str(exc).lower()
        exc_type = type(exc).__name__

        # Authentication errors
        if "401" in exc_str or "403" in exc_str or "unauthorized" in exc_str:
            raise AuthenticationError(
                source=self.SOURCE,
                message=f"Authentication failed for MPContribs{': ' + context if context else ''}",
            ) from exc

        # Rate limiting
        if "429" in exc_str or "rate limit" in exc_str:
            raise RateLimitError(
                source=self.SOURCE,
                message=f"Rate limit exceeded for MPContribs{': ' + context if context else ''}",
            ) from exc

        # Network errors
        if any(
            term in exc_str
            for term in ["connection", "timeout", "network", "unreachable"]
        ):
            raise NetworkError(source=self.SOURCE, original_error=exc) from exc

        # Generic API error
        raise MaterialsAPIError(
            message=f"MPContribs API error ({exc_type}){': ' + context if context else ''}: {exc}",
            source=self.SOURCE,
        ) from exc

    def _contribution_to_record(self, contrib: dict[str, Any]) -> ContributionRecord:
        """Convert raw MPContribs response to ContributionRecord.

        Args:
            contrib: Raw contribution dict from API

        Returns:
            ContributionRecord with normalized fields
        """
        # MPContribs returns contributions with varying field structures
        # The 'id' field is the contribution ID
        contribution_id = contrib.get("id", contrib.get("_id", ""))

        # Project can be nested or direct
        project = contrib.get("project", "")
        if isinstance(project, dict):
            project = project.get("name", project.get("id", ""))

        # Material ID linkage
        material_id = contrib.get("identifier", None)
        if material_id and not material_id.startswith("mp-"):
            # Some contributions use 'identifier' for non-MP IDs
            material_id = None

        # Formula extraction
        formula = contrib.get("formula", None)
        if not formula and "data" in contrib:
            formula = contrib["data"].get("formula", None)

        # Main data payload
        data = contrib.get("data", {})
        if not isinstance(data, dict):
            data = {}

        # Tables and structures (may be nested or list of IDs)
        tables = contrib.get("tables", [])
        if not isinstance(tables, list):
            tables = [tables] if tables else []

        structures = contrib.get("structures", [])
        if not isinstance(structures, list):
            structures = [structures] if structures else []

        return ContributionRecord(
            contribution_id=str(contribution_id),
            project=str(project),
            material_id=material_id,
            identifier=contrib.get("identifier"),
            formula=formula,
            data=data,
            tables=tables,
            structures=structures,
        )

    async def list_projects(self) -> list[dict[str, Any]]:
        """List all available MPContribs projects.

        Returns:
            List of project metadata dictionaries with keys:
            - name: Project name/identifier
            - title: Human-readable title
            - description: Project description
            - authors: List of author names
            - is_public: Whether project is publicly accessible

        Raises:
            AuthenticationError: If API key is invalid
            NetworkError: If connection fails
            MaterialsAPIError: For other API errors
        """

        def _sync_list_projects() -> list[dict[str, Any]]:
            client = self._get_sync_client()
            # The client.projects attribute gives access to project methods
            projects = client.projects.get_entries().result()
            return [
                {
                    "name": p.get("name", p.get("id", "")),
                    "title": p.get("title", ""),
                    "description": p.get("description", ""),
                    "authors": p.get("authors", []),
                    "is_public": p.get("is_public", True),
                }
                for p in projects.get("data", [])
            ]

        try:
            return await asyncio.to_thread(_sync_list_projects)
        except (AuthenticationError, RateLimitError, NetworkError, MaterialsAPIError):
            raise
        except Exception as exc:
            self._handle_exception(exc, context="listing projects")
            return []  # Unreachable, but satisfies type checker

    async def get_project(self, project: str) -> dict[str, Any]:
        """Get project metadata.

        Args:
            project: Project name/identifier

        Returns:
            Project metadata dictionary with keys:
            - name: Project name
            - title: Human-readable title
            - description: Detailed description
            - authors: List of author names
            - references: Citations and DOIs
            - columns: Available data columns
            - stats: Contribution counts

        Raises:
            StructureNotFoundError: If project doesn't exist
            AuthenticationError: If API key is invalid
            MaterialsAPIError: For other API errors
        """

        def _sync_get_project() -> dict[str, Any]:
            client = self._get_sync_client()
            try:
                project_data = client.projects.get_entry(name=project).result()
                return dict(project_data)
            except Exception as exc:
                if "404" in str(exc).lower() or "not found" in str(exc).lower():
                    raise StructureNotFoundError(
                        identifier=project,
                        source=self.SOURCE,
                        message=f"MPContribs project not found: {project}",
                    ) from exc
                raise

        try:
            return await asyncio.to_thread(_sync_get_project)
        except (
            AuthenticationError,
            RateLimitError,
            NetworkError,
            MaterialsAPIError,
            StructureNotFoundError,
        ):
            raise
        except Exception as exc:
            self._handle_exception(exc, context=f"getting project '{project}'")
            return {}  # Unreachable

    async def get_contributions(
        self,
        project: str,
        formula: str | None = None,
        material_id: str | None = None,
        limit: int = 50,
    ) -> list[ContributionRecord]:
        """Fetch contributions from a project.

        Args:
            project: MPContribs project name
            formula: Filter by chemical formula (e.g., 'GaAs')
            material_id: Filter by MP material ID (e.g., 'mp-149')
            limit: Maximum number of contributions to return

        Returns:
            List of ContributionRecord objects

        Raises:
            StructureNotFoundError: If project doesn't exist
            AuthenticationError: If API key is invalid
            MaterialsAPIError: For other API errors

        Example:
            records = await client.get_contributions(
                "carrier_transport",
                formula="Si",
                limit=10
            )
        """

        def _sync_get_contributions() -> list[dict[str, Any]]:
            client = self._get_sync_client()

            # Build query parameters
            query: dict[str, Any] = {"project": project, "_limit": limit}

            if formula:
                query["formula"] = formula
            if material_id:
                query["identifier"] = material_id

            try:
                result = client.contributions.get_entries(**query).result()
                return result.get("data", [])
            except Exception as exc:
                if "404" in str(exc).lower():
                    raise StructureNotFoundError(
                        identifier=project,
                        source=self.SOURCE,
                        message=f"MPContribs project not found: {project}",
                    ) from exc
                raise

        try:
            raw_contributions = await asyncio.to_thread(_sync_get_contributions)
            return [self._contribution_to_record(c) for c in raw_contributions]
        except (
            AuthenticationError,
            RateLimitError,
            NetworkError,
            MaterialsAPIError,
            StructureNotFoundError,
        ):
            raise
        except Exception as exc:
            self._handle_exception(
                exc, context=f"getting contributions from '{project}'"
            )
            return []  # Unreachable

    async def get_contribution_by_id(
        self,
        contribution_id: str,
    ) -> ContributionRecord:
        """Fetch a specific contribution by ID.

        Args:
            contribution_id: Unique contribution ID

        Returns:
            ContributionRecord for the specified contribution

        Raises:
            StructureNotFoundError: If contribution doesn't exist
            AuthenticationError: If API key is invalid
            MaterialsAPIError: For other API errors
        """

        def _sync_get_contribution() -> dict[str, Any]:
            client = self._get_sync_client()
            try:
                result = client.contributions.get_entry(cid=contribution_id).result()
                return dict(result)
            except Exception as exc:
                if "404" in str(exc).lower() or "not found" in str(exc).lower():
                    raise StructureNotFoundError(
                        identifier=contribution_id,
                        source=self.SOURCE,
                        message=f"MPContribs contribution not found: {contribution_id}",
                    ) from exc
                raise

        try:
            raw_contribution = await asyncio.to_thread(_sync_get_contribution)
            return self._contribution_to_record(raw_contribution)
        except (
            AuthenticationError,
            RateLimitError,
            NetworkError,
            MaterialsAPIError,
            StructureNotFoundError,
        ):
            raise
        except Exception as exc:
            self._handle_exception(
                exc, context=f"getting contribution '{contribution_id}'"
            )
            # Unreachable, but type checker wants a return
            raise MaterialsAPIError("Unexpected error", source=self.SOURCE) from exc

    async def search_by_material_id(
        self,
        material_id: str,
    ) -> list[ContributionRecord]:
        """Find all contributions for a material ID across all projects.

        This searches all public MPContribs projects for contributions
        linked to the specified Materials Project ID.

        Args:
            material_id: Materials Project ID (e.g., 'mp-149')

        Returns:
            List of ContributionRecord objects from all projects

        Raises:
            AuthenticationError: If API key is invalid
            MaterialsAPIError: For other API errors

        Example:
            # Find all experimental/computed data for silicon
            records = await client.search_by_material_id("mp-149")
            for r in records:
                print(f"Project: {r.project}, Data: {r.data}")
        """

        def _sync_search_by_material_id() -> list[dict[str, Any]]:
            client = self._get_sync_client()

            # Search across all projects with this identifier
            query: dict[str, Any] = {
                "identifier": material_id,
                "_limit": 100,  # Reasonable limit for cross-project search
            }

            try:
                result = client.contributions.get_entries(**query).result()
                return result.get("data", [])
            except Exception:
                # If the query fails, return empty rather than error
                # since the material might just not have any contributions
                logger.debug(
                    "No contributions found for material ID: %s", material_id
                )
                return []

        try:
            raw_contributions = await asyncio.to_thread(_sync_search_by_material_id)
            records = [self._contribution_to_record(c) for c in raw_contributions]
            logger.info(
                "Found %d contributions for material ID: %s",
                len(records),
                material_id,
            )
            return records
        except (
            AuthenticationError,
            RateLimitError,
            NetworkError,
            MaterialsAPIError,
        ):
            raise
        except Exception as exc:
            self._handle_exception(
                exc, context=f"searching contributions for '{material_id}'"
            )
            return []  # Unreachable
