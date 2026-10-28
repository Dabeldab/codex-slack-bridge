$logPath = "C:\Users\Darioso\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
Write-Output "=== full traceback around complete_google_login (19:07-19:09Z) ==="
$f = 'resource.type="cloud_run_revision" AND resource.labels.service_name="nova-command-center-shadow"'
$lines = & $logPath logging read $f --freshness=40h --format='value(timestamp,textPayload)' --project=gen-lang-client-0051653266
# find window: lines between 19:07 and 19:10, keep non-401
$sel = $lines | Where-Object { ($_ -match '2026-10-07T19:0[7-9]') -and ($_ -notmatch ' 401 -') }
$sel | ForEach-Object { Write-Output $_ }
