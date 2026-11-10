# ORBITE — MERIDIAN RISK ADVISORY

Application de finance d'entreprise, equity research, analyse financière et valorisation.

## Contenu
- `app.py` : application Streamlit complète.
- `requirements.txt` : dépendances Python.
- `run_orbite.bat` : lancement direct sans activer PowerShell.
- `orbite.db` : créée automatiquement au premier lancement, pour conserver les sociétés, états financiers et valorisations.

## Installation Windows
Ouvrir PowerShell dans ce dossier :

```powershell
py -3.15 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Si l'environnement `.venv` existe déjà et fonctionne, ne le recrée pas : lance simplement `run_orbite.bat`.

## Utilisation
1. Ouvrir Company Search et importer un ticker (ex. MSFT, AAPL, MC.PA).
2. Les données sont enregistrées dans `orbite.db`.
3. Corriger/compléter les états financiers dans Financial Statements.
4. Analyser dans Financial Analysis, valoriser dans Valuation et comparer dans Peer Comparison.
5. Exporter le modèle depuis Excel Center, puis réimporter le classeur après modification.

## Excel 365
L'application génère un classeur `.xlsx` avec Company Profile, Financial Statements, Financial Analysis, Key Ratios, Model Assumptions et Excel Model. Les calculs Excel natifs sont inclus. L'échange avec Streamlit se fait par import/export manuel de fichiers ; ce n'est pas une synchronisation OneDrive en temps réel.

## Données et précautions
Yahoo Finance/yfinance est une source indicative pour sociétés cotées. Les données peuvent être absentes, retardées ou classées différemment. Les normes comptables ne sont pas harmonisées automatiquement. Vérifier les sources, les définitions et les hypothèses avant tout usage professionnel ou décision d'investissement.
