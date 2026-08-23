"""
app/config.py — configurazione dell'applicazione Flask.

Legge i valori da variabili d'ambiente o dal file .env.
I valori di default sono sicuri solo per sviluppo locale:
in produzione TUTTE le chiavi devono essere sostituite con valori casuali.
"""

import os
from dotenv import load_dotenv

# Carica variabili dal file .env se presente
load_dotenv()


class Config:
    """
    Classe di configurazione principale.

    Tutti i parametri sensibili (chiavi, percorsi DB) vengono letti
    da variabili d'ambiente per evitare di committare segreti nel codice.
    """

    # -----------------------------------------------------------------------
    # Flask
    # -----------------------------------------------------------------------
    SECRET_KEY: str = os.environ.get(
        'SECRET_KEY', 'cambia-questa-chiave-flask-in-produzione'
    )
    FLASK_DEBUG: bool = os.environ.get('FLASK_DEBUG', '0') == '1'

    # -----------------------------------------------------------------------
    # Database Master (registro tenant + master admin)
    # -----------------------------------------------------------------------
    MASTER_DB_PATH: str = os.environ.get('MASTER_DB_PATH', 'master.db')
    """Percorso del file master.db cifrato con SQLCipher."""

    MASTER_DB_KEY: str = os.environ.get(
        'MASTER_DB_KEY', 'cambia-questa-chiave-master-in-produzione'
    )
    """Chiave di cifratura AES-256 del master database."""

    # -----------------------------------------------------------------------
    # Database Tenant (un file SQLCipher per organizzazione)
    # -----------------------------------------------------------------------
    TENANT_DB_DIR: str = os.environ.get('TENANT_DB_DIR', 'tenants/')
    """Directory contenente i file .db dei tenant."""

    TEMPLATE_DB_DIR: str = os.environ.get('TEMPLATE_DB_DIR', 'templates/')
    """Directory contenente i file .db dei template tenant."""

    TENANT_KEYS_PATH: str = os.environ.get(
        'TENANT_KEYS_PATH', 'tenant_keys.json'
    )
    """Percorso del file JSON con le chiavi di cifratura per tenant/template."""

    # -----------------------------------------------------------------------
    # JWT
    # -----------------------------------------------------------------------
    JWT_SECRET_KEY: str = os.environ.get(
        'JWT_SECRET_KEY', 'cambia-questa-chiave-jwt-in-produzione'
    )
    JWT_ACCESS_TOKEN_EXPIRES: int = int(
        os.environ.get('JWT_ACCESS_TOKEN_EXPIRES', 3600)
    )
    """Durata del token JWT in secondi. Default: 3600 (1 ora)."""

    JWT_TOKEN_LOCATION: list = ['headers']
    JWT_HEADER_NAME: str = 'Authorization'
    JWT_HEADER_TYPE: str = 'Bearer'

    # -----------------------------------------------------------------------
    # Regole di business
    # -----------------------------------------------------------------------
    MAX_HISTORY_STEPS: int = int(os.environ.get('MAX_HISTORY_STEPS', 500))
    """Numero massimo di step nella history per singolo calendario."""

    ORE_GIORNALIERE_DEFAULT: float = float(
        os.environ.get('ORE_GIORNALIERE_DEFAULT', 6.5)
    )
    """Ore lavorative giornaliere di default (6.5 = 6h 30m)."""
