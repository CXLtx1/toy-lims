$env:LIMS_DATABASE_URL = "postgresql://cxltx:qwe123qwe123@192.168.2.4:5432/toy_lims"
$env:LIMS_XRF_CLIENT_TOKEN = "xrf-test-token"
$env:LIMS_STANDARD_CLIENT_TOKEN = "standard-test-token"

Set-Location $PSScriptRoot
python server.py
