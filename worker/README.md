Cloudflare Worker that replaces GitHub's own 30-minute cron (see index.js). Deploy: dashboard -> Workers & Pages ->
Create -> paste index.js -> Triggers -> Cron `*/30 * * * *`. Secret `GH_TOKEN` = fine-grained GitHub token
(repo stoic-automation only, Actions: Read and write). No other permissions.
