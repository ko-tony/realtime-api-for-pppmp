# PPPMP Data API

PPPMP 廣告使用的公開附屬資料 API，提供天氣、空氣品質及台灣股市大盤資料。

## API

對外資料 endpoints：

- `GET /api/v1/environment`
- `GET /api/v1/finance`：台灣加權指數與當日累計成交金額（億元），回傳單一物件。
  擷取程式、建表與每 3 分鐘排程設定見 [Finance 部署說明](cloudrun/README-finance.md)。

回傳各縣市的空氣品質與天氣即時值，由 `moenv_live` 與 `cwa_uv_live` 依縣市 JOIN 而成：

| 欄位 | 來源 | 說明 |
| --- | --- | --- |
| `cityName` | moenv | 縣市名，含「市」 |
| `aqi`、`pm25`、`o3` | moenv | 測站維修時為 `null` |
| `aqiDate` | moenv | 環境部發布時間 |
| `airTemperature`、`humidity`、`uvIndex`、`weather` | cwa | |
| `maxTemperature`、`minTemperature` | cwa | 測站當日截至觀測時間的最高／最低溫（攝氏），缺測為 `null` |
| `weatherDate` | cwa | 測站觀測時間 |

兩個時間欄位都是 `timestamptz`，回傳帶 `+08:00` 偏移。兩表縣市名格式不同（`臺北市` / `臺北`），JOIN 時以 `replace(cityName, '市', '')` 對齊。

舊路徑 `/cwa_uv_live`、`/moenv_live`、`/env_live_1` 與 `/api/v1/cwa-uv-live`、`/api/v1/air-quality` 已移除。`/weather`、帳號、OAuth 測試與 Excel 轉 Word 功能亦已移除。

## 資料擷取

`cloudrun/` 的寫入端各自由 Cloud Scheduler 定時觸發，把來源 API 的資料 upsert 進 PostgreSQL：

| 服務 | 資料來源 | 寫入 |
| --- | --- | --- |
| `get-cwa-uv-live` | 中央氣象署 O-A0003-001 | `cwa_uv_live` |
| `get-moenv-aqi-live-1` | 環境部 aqx_p_432 | `moenv_live` |
| `get-twse-finance-live` | 證交所 getChartOhlcStatis | `finance_live` |

`config.py` 負責環境變數，`db.py` 提供共用的 `upsert_rows()`。新增第三個資料源時，準備好表名與欄位順序即可直接呼叫，不需再寫一次 SQL。

最高／最低溫取自 CWA `WeatherElement.DailyExtreme.DailyHigh/DailyLow.TemperatureInfo.AirTemperature`，是當日觀測極值。部署擷取程式與公開 API 前，先以資料表擁有者執行 [`cloudrun/cwa-uv-live.sql`](cloudrun/cwa-uv-live.sql) 新增兩個欄位；既有資料等下次擷取成功後補值。欄位與缺測代碼見 [CWA 資料標準](https://opendata.cwa.gov.tw/opendatadoc/Observation/O-A0003-001.pdf)。

### 環境變數

| 變數 | 來源 | 值 |
| --- | --- | --- |
| `DB_HOST` | env var | `/cloudsql/PROJECT:REGION:INSTANCE` |
| `DB_USER` | env var | `ingest_user` |
| `DB_PASSWORD` | Secret Manager | `INGEST_DB_PASSWORD:latest` |
| `CWA_API_TOKEN` / `MOENV_API_KEY` | env var | 各自的政府 API 金鑰 |
| `DB_NAME` | 可省略 | 預設 `postgres` |
| `HTTP_TIMEOUT_SECONDS` | 可省略 | 預設 `15` |

缺少必填變數時會在請求當下拋 `RuntimeError` 並寫進 Cloud Logging，不會帶著空值連線。

### 部署

```bash
CONN=PROJECT:REGION:INSTANCE

gcloud run services update get-cwa-uv-live --region=asia-east1 \
  --add-cloudsql-instances=$CONN \
  --update-env-vars="^@^DB_HOST=/cloudsql/$CONN@DB_USER=ingest_user@CWA_API_TOKEN=<金鑰>" \
  --set-secrets=DB_PASSWORD=INGEST_DB_PASSWORD:latest
```

三個容易踩到的點：

- `--add-cloudsql-instances` 沒下，容器裡就不會有 `/cloudsql/` socket，錯誤是 `No such file or directory`。runtime service account 少了 `roles/cloudsql.client` 也是同樣症狀。
- `--set-env-vars` 是整組覆蓋，追加要用 `--update-env-vars`。
- 這兩支是 gen2 function，用 `gcloud functions deploy` 重新部署可能會蓋掉 Cloud SQL 掛載設定，部署後要補跑一次 `gcloud run services update`。

### 權限

- 寫入端使用 `ingest_user`，只有這兩張表的 `SELECT, INSERT, UPDATE`。
- Cloud Scheduler 以專屬 service account 帶 OIDC token 呼叫，該 SA 只有 `roles/run.invoker`。
- 兩支服務均為「需要驗證」且已移除 `allUsers` binding。

## 本機執行

環境變數：

```dotenv
SQLALCHEMY_DATABASE_URL=postgresql://user:password@host:5432/database
DB_SSLMODE=require
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=2
DB_CONNECT_TIMEOUT_SECONDS=5
BROWSER_CACHE_SECONDS=30
SHARED_CACHE_SECONDS=300
STALE_WHILE_REVALIDATE_SECONDS=600
```

直接 TCP 連線使用 `require`、`verify-ca` 或 `verify-full`。Cloud Run 透過 Cloud SQL Unix Socket 連線時，URL 使用 `?host=/cloudsql/PROJECT:REGION:INSTANCE`，並設定 `DB_SSLMODE=disable`；此處的 `disable` 只關閉 container 到本機 socket 的 libpq TLS，Cloud SQL 整合仍負責 socket 後端連線的加密與授權。程式會拒絕一般 TCP URL 使用 `disable`。

啟動與測試：

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload
# 執行包含 Cloud Run 擷取程式的測試時，另安裝擷取依賴
.venv/bin/pip install -r requirements.txt -r cloudrun/requirements.txt
.venv/bin/python -m unittest discover
```

- API 文件：`http://127.0.0.1:8000/docs`
- Liveness：`GET /health`
- Database readiness：`GET /ready`

## 部署方向

現有網域與 External Application Load Balancer 可繼續沿用。短期可部署在既有 Managed Instance Group，但應改用固定版本 artifact、systemd 與 MIG rolling update，不再於 VM 開機時直接 `git pull`。較省維運的目標是把 Load Balancer backend 換成 Cloud Run serverless NEG；Cloud Run ingress 設為 `internal-and-cloud-load-balancing`，避免直接繞過 CDN/Armor。

資料庫密碼已改由 Secret Manager 提供（見上方「資料擷取」）。完整研究與遷移清單見 [`docs/deployment-security-research.md`](docs/deployment-security-research.md)。
