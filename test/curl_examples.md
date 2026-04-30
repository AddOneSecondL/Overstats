# Overstats Curl Examples

```bat
curl.exe -X POST "http://127.0.0.1:18080/api/v2/dashen-profile" ^
  -H "Content-Type: application/json; charset=utf-8" ^
  -d "{\"bnet_id\":\"oL1ama#5684\"}" ^
  --output dashen-profile.json

curl.exe -X POST "http://127.0.0.1:18080/api/v2/dashen-profile/image" ^
  -H "Content-Type: application/json; charset=utf-8" ^
  -d "{\"bnet_id\":\"oL1ama#5684\"}" ^
  --output dashen-profile-quick.png

curl.exe -X POST "http://127.0.0.1:18080/api/v2/dashen-match" ^
  -H "Content-Type: application/json; charset=utf-8" ^
  -d "{\"bnet_id\":\"oL1ama#5684\"}" ^
  --output dashen-match.json

curl.exe -X POST "http://127.0.0.1:18080/api/v2/dashen-match/replies" ^
  -H "Content-Type: application/json; charset=utf-8" ^
  -d "{\"bnet_id\":\"oL1ama#5684\",\"limit\":20}" ^
  --output dashen-match-replies.json

curl.exe -X POST "http://127.0.0.1:18080/api/v2/dashen-match/detail" ^
  -H "Content-Type: application/json; charset=utf-8" ^
  -d "{\"bnet_id\":\"oL1ama#5684\",\"index\":0}" ^
  --output dashen-match-detail.json

curl.exe -X POST "http://127.0.0.1:18080/api/v2/dashen-match/detail/replies" ^
  -H "Content-Type: application/json; charset=utf-8" ^
  -d "{\"bnet_id\":\"oL1ama#5684\",\"index\":0}" ^
  --output dashen-match-detail-replies.json

curl.exe -X POST "http://127.0.0.1:18080/api/v2/dashen-match/detail/replies" ^
  -H "Content-Type: application/json; charset=utf-8" ^
  -d "{\"bnet_id\":\"oL1ama#5684\",\"index\":0,\"show_all_heroes\":true}" ^
  --output dashen-match-detail-all-players.json

curl.exe -X POST "http://127.0.0.1:18080/api/v2/dashen-match/detail/replies" ^
  -H "Content-Type: application/json; charset=utf-8" ^
  -d "{\"bnet_id\":\"oL1ama#5684\",\"index\":0,\"show_all_heroes\":true,\"analyze\":true}" ^
  --output dashen-match-detail-analysis.json

curl.exe -X POST "http://127.0.0.1:18080/api/v2/dashen-summary/today" ^
  -H "Content-Type: application/json; charset=utf-8" ^
  -d "{\"bnet_id\":\"oL1ama#5684\"}" ^
  --output dashen-summary-today.json

curl.exe -X POST "http://127.0.0.1:18080/api/v2/dashen-summary/today/image" ^
  -H "Content-Type: application/json; charset=utf-8" ^
  -d "{\"bnet_id\":\"oL1ama#5684\"}" ^
  --output dashen-summary-today.jpg

curl.exe -X POST "http://127.0.0.1:18080/api/v2/dashen-summary/yesterday" ^
  -H "Content-Type: application/json; charset=utf-8" ^
  -d "{\"bnet_id\":\"oL1ama#5684\"}" ^
  --output dashen-summary-yesterday.json

curl.exe -X POST "http://127.0.0.1:18080/api/v2/dashen-summary/yesterday/image" ^
  -H "Content-Type: application/json; charset=utf-8" ^
  -d "{\"bnet_id\":\"oL1ama#5684\"}" ^
  --output dashen-summary-yesterday.jpg

curl.exe -X POST "http://127.0.0.1:18080/api/v2/dashen-summary/week" ^
  -H "Content-Type: application/json; charset=utf-8" ^
  -d "{\"bnet_id\":\"oL1ama#5684\"}" ^
  --output dashen-summary-week.json

curl.exe -X POST "http://127.0.0.1:18080/api/v2/dashen-summary/week/image" ^
  -H "Content-Type: application/json; charset=utf-8" ^
  -d "{\"bnet_id\":\"oL1ama#5684\"}" ^
  --output dashen-summary-week.jpg

curl.exe -X POST "http://127.0.0.1:18080/api/v2/dashen-rank-history" ^
  -H "Content-Type: application/json; charset=utf-8" ^
  -d "{\"bnet_id\":\"oL1ama#5684\"}" ^
  --output dashen-rank-history.json

curl.exe -X POST "http://127.0.0.1:18080/api/v2/dashen-rank-history/image" ^
  -H "Content-Type: application/json; charset=utf-8" ^
  -d "{\"bnet_id\":\"oL1ama#5684\"}" ^
  --output dashen-rank-history.png

curl.exe -X POST "http://127.0.0.1:18080/api/v2/ow-hero-pick-rate" ^
  -H "Content-Type: application/json; charset=utf-8" ^
  -d "{\"view\":\"ranking\",\"game_mode\":\"quick\",\"mmr\":\"all\"}" ^
  --output ow-hero-pick-rate-ranking.json

curl.exe -X POST "http://127.0.0.1:18080/api/v2/ow-hero-pick-rate/image" ^
  -H "Content-Type: application/json; charset=utf-8" ^
  -d "{\"view\":\"history\",\"game_mode\":\"competitive\",\"mmr\":\"Master\",\"hero\":\"安娜\",\"history_limit\":20}" ^
  --output ow-hero-pick-rate-history.png
```
