import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
import os
import requests
import json
import re
from datetime import datetime, timedelta

# 載入環境變數
load_dotenv()

class TPVLLocalUpdater:
    def __init__(self):
        # 資料庫連線參數
        self.db_config = {
            'user': os.getenv("user"),
            'password': os.getenv("password"),
            'host': os.getenv("host"),
            'port': os.getenv("port"),
            'dbname': os.getenv("dbname")
        }
        
        self.base_url = "https://www.tpvl.tw/schedule/schedule"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        self.connection = None
        self.cursor = None
    
    def connect(self):
        """連接到資料庫"""
        try:
            # 為 Pooler 連線添加特殊參數
            connection_params = self.db_config.copy()
            
            # 如果使用 Pooler,添加這些參數
            if 'pooler.supabase.com' in connection_params.get('host', ''):
                print("  檢測到 Pooler 連線,使用最佳化設定...")
                connection_params['options'] = '-c statement_timeout=60000'
            
            self.connection = psycopg2.connect(**connection_params)
            self.cursor = self.connection.cursor()
            
            # 測試連線
            self.cursor.execute("SELECT 1")
            
            print("✅ 資料庫連線成功!")
            return True
        except Exception as e:
            print(f"❌ 資料庫連線失敗: {e}")
            return False
    
    def close(self):
        """關閉連線"""
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
        print("✅ 資料庫連線已關閉")
    
    def create_tables(self):
        """建立 TPVL 相關資料表"""
        print("\n📊 建立資料表...")
        
        # 如果表格已存在則先刪除 (測試用)
        # drop_sql = """
        # DROP TABLE IF EXISTS tpvl_gathering_participants CASCADE;
        # DROP TABLE IF EXISTS tpvl_gatherings CASCADE;
        # DROP TABLE IF EXISTS tpvl_matches CASCADE;
        # DROP TABLE IF EXISTS tpvl_teams CASCADE;
        # """
        
        create_sql = """
        -- 1. 球隊表
        CREATE TABLE IF NOT EXISTS tpvl_teams (
            id BIGINT PRIMARY KEY,
            name TEXT NOT NULL,
            name_en TEXT,
            logo_url TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        
        -- 2. 比賽表
        CREATE TABLE IF NOT EXISTS tpvl_matches (
            id BIGINT PRIMARY KEY,
            code TEXT NOT NULL,
            match_date DATE NOT NULL,
            match_time TIME NOT NULL,
            weekday TEXT,
            home_team_id BIGINT REFERENCES tpvl_teams(id),
            away_team_id BIGINT REFERENCES tpvl_teams(id),
            venue TEXT NOT NULL,
            status TEXT DEFAULT 'upcoming',
            home_score INTEGER,
            away_score INTEGER,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        
        -- 建立索引
        CREATE INDEX IF NOT EXISTS idx_tpvl_matches_date ON tpvl_matches(match_date);
        CREATE INDEX IF NOT EXISTS idx_tpvl_matches_status ON tpvl_matches(status);
        """
        
        try:
            # self.cursor.execute(drop_sql)  # 測試時可開啟
            self.cursor.execute(create_sql)
            self.connection.commit()
            print("  ✅ 資料表建立成功")
            return True
        except Exception as e:
            print(f"  ❌ 建立資料表失敗: {e}")
            self.connection.rollback()
            return False
    
    def extract_json_data(self, html):
        """從 HTML 提取 JSON"""
        pattern = r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>'
        match = re.search(pattern, html, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        return None
    
    def fetch_schedule(self, result_page=1, future_page=1):
        """抓取賽程"""
        url = f"{self.base_url}?resultPage={result_page}&futurePage={future_page}"
        
        try:
            print(f"  抓取: 第{result_page}頁賽果 / 第{future_page}頁未來...")
            response = requests.get(url, headers=self.headers, timeout=15)
            response.raise_for_status()
            
            data = self.extract_json_data(response.text)
            if not data:
                return None, None
            
            page_props = data['props']['pageProps']
            
            result_matches = page_props.get('resultMatchData', {}).get('data', [])
            future_matches = page_props.get('incomingMatch', {}).get('data', [])
            squads = page_props.get('squads', [])
            
            return {
                'results': result_matches,
                'futures': future_matches,
                'squads': squads
            }
            
        except Exception as e:
            print(f"  ❌ 抓取失敗: {e}")
            return None
    
    def upsert_teams(self, teams_data):
        """更新球隊資料 (Upsert)"""
        print("\n🏐 更新球隊資料...")
        
        # 使用 ON CONFLICT ... DO UPDATE 實現 upsert
        sql = """
        INSERT INTO tpvl_teams (id, name, name_en, logo_url, updated_at)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            name_en = EXCLUDED.name_en,
            logo_url = EXCLUDED.logo_url,
            updated_at = NOW()
        """
        
        values = [
            (
                team['id'],
                team['name'],
                team['altName'],
                team['logoUrl'],
                datetime.now()
            )
            for team in teams_data
        ]
        
        try:
            execute_values(self.cursor, sql, values)
            self.connection.commit()
            print(f"  ✅ 成功更新 {len(values)} 支球隊")
            
            # 顯示球隊列表
            for team in teams_data:
                print(f"    - {team['name']} ({team['altName']})")
            
        except Exception as e:
            print(f"  ❌ 更新失敗: {e}")
            self.connection.rollback()
    
    def parse_match(self, match_data):
        """解析比賽資料"""
        # UTC -> 台北時間
        matched_at = match_data['matchedAt']
        dt = datetime.fromisoformat(matched_at.replace('Z', '+00:00'))
        taipei_dt = dt + timedelta(hours=8)
        
        # 處理比分
        status = 'upcoming'
        home_score = None
        away_score = None
        
        if match_data.get('squadMatchResults'):
            status = 'completed'
            for result in match_data['squadMatchResults']:
                if result['squadId'] == match_data['homeSquadId']:
                    home_score = result['wonRounds']
                elif result['squadId'] == match_data['awaySquadId']:
                    away_score = result['wonRounds']
        
        return (
            match_data['id'],
            match_data['code'],
            taipei_dt.date(),
            taipei_dt.time(),
            ['一', '二', '三', '四', '五', '六', '日'][taipei_dt.weekday()],
            match_data['homeSquadId'],
            match_data['awaySquadId'],
            match_data['venue'],
            status,
            home_score,
            away_score,
            datetime.now()
        )
    
    def upsert_matches(self, matches_data):
        """更新比賽資料"""
        print(f"\n⚡ 更新 {len(matches_data)} 場比賽...")
        
        sql = """
        INSERT INTO tpvl_matches 
        (id, code, match_date, match_time, weekday, home_team_id, away_team_id, 
         venue, status, home_score, away_score, updated_at)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            code = EXCLUDED.code,
            match_date = EXCLUDED.match_date,
            match_time = EXCLUDED.match_time,
            weekday = EXCLUDED.weekday,
            home_team_id = EXCLUDED.home_team_id,
            away_team_id = EXCLUDED.away_team_id,
            venue = EXCLUDED.venue,
            status = EXCLUDED.status,
            home_score = EXCLUDED.home_score,
            away_score = EXCLUDED.away_score,
            updated_at = NOW()
        """
        
        values = [self.parse_match(m) for m in matches_data]
        
        try:
            execute_values(self.cursor, sql, values)
            self.connection.commit()
            print(f"  ✅ 成功更新 {len(values)} 場比賽")
            
            # 顯示最近5場
            print("\n  最近的比賽:")
            for match in matches_data[:5]:
                parsed = self.parse_match(match)
                date, time, weekday = parsed[2], parsed[3], parsed[4]
                home_id, away_id = parsed[5], parsed[6]
                venue = parsed[7]
                print(f"    場次{parsed[1]}: {date}({weekday}) {time} @ {venue}")
            
        except Exception as e:
            print(f"  ❌ 更新失敗: {e}")
            self.connection.rollback()
    
    def run(self):
        """執行完整更新流程"""
        print("=" * 60)
        print("🚀 TPVL 本地更新程式 (psycopg2 版本)")
        print("=" * 60)
        print(f"⏰ 執行時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        # 1. 連接資料庫
        if not self.connect():
            return
        
        # 2. 建立資料表
        if not self.create_tables():
            self.close()
            return
        
        # 3. 抓取資料
        print("\n🌐 開始抓取賽程資料...")
        all_matches = []
        all_squads = []
        
        # 第一頁 (包含球隊資料)
        data = self.fetch_schedule(result_page=1, future_page=1)
        if data:
            all_squads = data['squads']
            all_matches.extend(data['results'])
            all_matches.extend(data['futures'])
        
        # 過去賽果 (2-4頁)
        for page in range(2, 5):
            data = self.fetch_schedule(result_page=page, future_page=1)
            if data and data['results']:
                all_matches.extend(data['results'])
        
        # 未來賽程 (第2頁)
        data = self.fetch_schedule(result_page=1, future_page=2)
        if data and data['futures']:
            all_matches.extend(data['futures'])
        
        # 去重
        unique_matches = {m['id']: m for m in all_matches}.values()
        
        print(f"\n📊 抓取結果:")
        print(f"  - 球隊: {len(all_squads)} 支")
        print(f"  - 比賽: {len(unique_matches)} 場")
        
        # 4. 更新球隊
        if all_squads:
            self.upsert_teams(all_squads)
        
        # 5. 更新比賽
        if unique_matches:
            self.upsert_matches(list(unique_matches))
        
        # 6. 驗證資料
        self.verify_data()
        
        # 7. 關閉連線
        self.close()
        
        print("\n" + "=" * 60)
        print("✅ 更新完成!")
        print("=" * 60)
    
    def verify_data(self):
        """驗證資料"""
        print("\n🔍 驗證資料...")
        
        # 檢查球隊數量
        self.cursor.execute("SELECT COUNT(*) FROM tpvl_teams")
        team_count = self.cursor.fetchone()[0]
        print(f"  ✅ 球隊總數: {team_count}")
        
        # 檢查比賽數量
        self.cursor.execute("SELECT COUNT(*) FROM tpvl_matches")
        match_count = self.cursor.fetchone()[0]
        print(f"  ✅ 比賽總數: {match_count}")
        
        # 檢查即將開始的比賽
        self.cursor.execute("""
            SELECT COUNT(*) FROM tpvl_matches 
            WHERE match_date >= CURRENT_DATE 
            AND status = 'upcoming'
        """)
        upcoming_count = self.cursor.fetchone()[0]
        print(f"  ✅ 未來賽程: {upcoming_count} 場")
        
        # 檢查已完成的比賽
        self.cursor.execute("""
            SELECT COUNT(*) FROM tpvl_matches 
            WHERE status = 'completed'
        """)
        completed_count = self.cursor.fetchone()[0]
        print(f"  ✅ 已完成: {completed_count} 場")

if __name__ == "__main__":
    try:
        updater = TPVLLocalUpdater()
        updater.run()
    except Exception as e:
        print(f"\n❌ 執行失敗: {e}")
        import traceback
        traceback.print_exc()