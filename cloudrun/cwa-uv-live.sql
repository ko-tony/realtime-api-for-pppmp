-- 先以資料表擁有者執行，再部署擷取程式與公開 API。可重複執行。
ALTER TABLE public.cwa_uv_live
    ADD COLUMN IF NOT EXISTS "maxTemperature" double precision,
    ADD COLUMN IF NOT EXISTS "minTemperature" double precision;

COMMENT ON COLUMN public.cwa_uv_live."maxTemperature" IS '測站當日截至觀測時間最高溫（攝氏）；缺測為 NULL';
COMMENT ON COLUMN public.cwa_uv_live."minTemperature" IS '測站當日截至觀測時間最低溫（攝氏）；缺測為 NULL';
