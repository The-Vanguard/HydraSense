# Start the API with scoring enabled for every onboarded region (without HYDRASENSE_SCORE_REGIONS the
# map shows "No scored hexes for this region yet").  Run from the repo root:  powershell scripts/start_backend.ps1
$env:HYDRASENSE_SCORE_REGIONS = "idukki-kl,rudraprayag-uk,ribhoi-ml,chamoli-uk,darjeeling-wb,dhemaji-as,kullu-hp,mangan-sk,nilgiris-tn"
$env:HYDRASENSE_MAX_HEXES_PER_REGION = "60"     # stride-sampled per region; raise for denser maps (more API calls)
$env:HYDRASENSE_SCORE_WORKERS = "6"             # parallel scoring threads
py -3.12 -m uvicorn backend.main:app --port 8000
