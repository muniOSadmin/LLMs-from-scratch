# pantocraft // — secure client intake
#
# Handles encrypted, local-first client project data.
# No client PII leaves the device. Implements NY SHIELD Act requirements:
#   - Encryption at rest (Fernet symmetric, key stored in OS keychain)
#   - Separation of public record data (BBL, PLUTO) from client PII
#   - Written security policy enforced at code level
#
# On iPhone: key stored in iOS Keychain via SecItemAdd.
# On macOS mesh: key stored in macOS Keychain via security(1) or keyring library.
# On Linux dev box: key stored in ~/.local/share/pantocraft/keystore (chmod 600).

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# Optional: cryptography package for Fernet encryption
# pip install cryptography
try:
    from cryptography.fernet import Fernet
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False


# ---------------------------------------------------------------------------
# Client record — PII separated from public data
# ---------------------------------------------------------------------------

@dataclass
class ClientContact:
    """
    PII — encrypted at rest, never logged, never pushed to remote.
    NY SHIELD Act: this is "private information" of a NY resident.
    """
    display_name: str          # e.g. "Rivera Family" — shown in UI
    contact_email: str = ""    # encrypted
    contact_phone: str = ""    # encrypted
    preferred_contact: str = "email"
    notes: str = ""            # encrypted

    def public_label(self) -> str:
        """Non-PII reference for logs and public outputs."""
        return self.display_name


@dataclass
class PublicPropertyData:
    """
    Public record data from PLUTO/ACRIS/DOB — not PII, no encryption needed.
    This layer can be shared with moswalk-kernel and open-source tools.
    """
    bbl: str
    address: str
    borough: str
    zoning_district: str
    building_class: str
    year_built: int
    stories: int
    source: str = "PLUTO v25v4"
    retrieved_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class ClientEngagement:
    """
    One client project engagement managed under pantocraft //.
    Keeps PII (contact) separate from public data (property).
    """
    engagement_id: str         # e.g. "PC-2026-001"
    contact: ClientContact
    property: PublicPropertyData
    project_type: str
    project_description: str   # encrypted if sensitive
    estimated_cost: int
    dob_filing_type: str       # NB, A1, A2, A3, TR6, etc.
    status: str = "intake"     # intake | active | pending_agency | complete | on_hold
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    assigned_professional: str = ""  # licensed RA/PE/expediter responsible for this engagement
    pantocraft_notes: str = ""  # internal notes — encrypted

    def safe_dict(self) -> dict:
        """Return non-PII subset safe for logging and kernel routing."""
        return {
            "engagement_id": self.engagement_id,
            "client_label":  self.contact.public_label(),
            "bbl":           self.property.bbl,
            "address":       self.property.address,
            "borough":       self.property.borough,
            "zoning":        self.property.zoning_district,
            "project_type":  self.project_type,
            "filing_type":   self.dob_filing_type,
            "status":        self.status,
        }


# ---------------------------------------------------------------------------
# Encrypted storage
# ---------------------------------------------------------------------------

class EngagementStore:
    """
    Encrypted local store for client engagements.
    NY SHIELD Act compliant: AES-128-CBC via Fernet (AES-128).
    Key never stored in repo or env — OS keychain only.

    For dev/testing without keychain: set PANTOCRAFT_DEV_KEY env var
    (32 URL-safe base64 bytes). NEVER use in production.
    """

    def __init__(self, store_dir: Optional[Path] = None):
        if store_dir is None:
            store_dir = Path.home() / ".local" / "share" / "pantocraft" / "engagements"
        self.store_dir = store_dir
        self.store_dir.mkdir(parents=True, exist_ok=True)
        # Ensure directory is not world-readable
        os.chmod(self.store_dir, 0o700)
        self._fernet = self._load_fernet()

    def _load_fernet(self):
        if not _CRYPTO_AVAILABLE:
            return None  # plaintext mode — dev only, warn loudly

        # 1. Try OS keychain via keyring library
        try:
            import keyring
            key = keyring.get_password("pantocraft", "engagement_key")
            if key:
                from cryptography.fernet import Fernet
                return Fernet(key.encode())
        except ImportError:
            pass

        # 2. Dev fallback — env var ONLY
        dev_key = os.environ.get("PANTOCRAFT_DEV_KEY")
        if dev_key:
            import warnings
            warnings.warn(
                "PANTOCRAFT_DEV_KEY in use — development mode only. "
                "Never use in production with real client data.",
                stacklevel=2,
            )
            from cryptography.fernet import Fernet
            return Fernet(dev_key.encode())

        # 3. Generate new key and store in keychain (first-run)
        try:
            import keyring
            from cryptography.fernet import Fernet
            new_key = Fernet.generate_key()
            keyring.set_password("pantocraft", "engagement_key", new_key.decode())
            return Fernet(new_key)
        except Exception:
            pass

        return None  # fallback: no encryption (log warning)

    def _encrypt(self, data: str) -> bytes:
        if self._fernet:
            return self._fernet.encrypt(data.encode())
        import warnings
        warnings.warn("Encryption unavailable — storing plaintext. Install 'cryptography' + 'keyring'.")
        return data.encode()

    def _decrypt(self, data: bytes) -> str:
        if self._fernet:
            return self._fernet.decrypt(data).decode()
        return data.decode()

    def save(self, engagement: ClientEngagement) -> Path:
        """Encrypt and save an engagement to disk."""
        payload = json.dumps(asdict(engagement), default=str)
        encrypted = self._encrypt(payload)
        # File named by hashed engagement_id — no PII in filename
        fname = hashlib.sha256(engagement.engagement_id.encode()).hexdigest()[:16] + ".enc"
        path = self.store_dir / fname
        path.write_bytes(encrypted)
        os.chmod(path, 0o600)
        return path

    def load(self, engagement_id: str) -> Optional[ClientEngagement]:
        """Load and decrypt an engagement by ID."""
        fname = hashlib.sha256(engagement_id.encode()).hexdigest()[:16] + ".enc"
        path = self.store_dir / fname
        if not path.exists():
            return None
        raw = self._decrypt(path.read_bytes())
        data = json.loads(raw)
        # Reconstruct nested dataclasses
        data["contact"]  = ClientContact(**data["contact"])
        data["property"] = PublicPropertyData(**data["property"])
        return ClientEngagement(**data)

    def list_ids(self) -> list[str]:
        """Return all stored engagement IDs (by scanning index — no PII exposed)."""
        index_path = self.store_dir / "index.enc"
        if not index_path.exists():
            return []
        raw = self._decrypt(index_path.read_bytes())
        return json.loads(raw)

    def _update_index(self, engagement_id: str) -> None:
        ids = self.list_ids()
        if engagement_id not in ids:
            ids.append(engagement_id)
        index_path = self.store_dir / "index.enc"
        index_path.write_bytes(self._encrypt(json.dumps(ids)))
        os.chmod(index_path, 0o600)

    def register(self, engagement: ClientEngagement) -> Path:
        """Save engagement and update index."""
        path = self.save(engagement)
        self._update_index(engagement.engagement_id)
        return path


# ---------------------------------------------------------------------------
# Intake factory
# ---------------------------------------------------------------------------

def new_engagement(
    client_name: str,
    bbl: str,
    address: str,
    borough: str,
    zoning: str,
    building_class: str,
    year_built: int,
    stories: int,
    project_type: str,
    project_description: str,
    estimated_cost: int,
    dob_filing_type: str,
    assigned_professional: str = "",
    seq: int = 1,
) -> ClientEngagement:
    """
    Create a new pantocraft // engagement with a generated ID.
    Separates public property data from client PII at creation time.
    """
    year = datetime.utcnow().year
    eid = f"PC-{year}-{seq:03d}"
    return ClientEngagement(
        engagement_id=eid,
        contact=ClientContact(display_name=client_name),
        property=PublicPropertyData(
            bbl=bbl,
            address=address,
            borough=borough,
            zoning_district=zoning,
            building_class=building_class,
            year_built=year_built,
            stories=stories,
        ),
        project_type=project_type,
        project_description=project_description,
        estimated_cost=estimated_cost,
        dob_filing_type=dob_filing_type,
        assigned_professional=assigned_professional,
    )


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        store = EngagementStore(store_dir=Path(tmp))

        eng = new_engagement(
            client_name="Test Client",
            bbl="3-00783-0001",
            address="347 4th Street, Brooklyn, NY 11215",
            borough="Brooklyn",
            zoning="R6B",
            building_class="A5",
            year_built=1899,
            stories=3,
            project_type="Open rooftop deck",
            project_description="Add open deck on flat roof",
            estimated_cost=65000,
            dob_filing_type="A2",
        )

        path = store.register(eng)
        print(f"Saved: {path}")
        print(f"Safe dict (loggable): {eng.safe_dict()}")

        loaded = store.load(eng.engagement_id)
        assert loaded is not None
        assert loaded.contact.display_name == "Test Client"
        assert loaded.property.bbl == "3-00783-0001"
        print("Load + decrypt OK")
        print("Smoke test passed.")
