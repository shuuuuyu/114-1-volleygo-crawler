# 🏐 TVL/TPVL 排球賽程自動爬蟲

自動爬取台灣企業甲級排球聯賽 (TVL) 和台北市男子排球聯賽 (TPVL) 的賽程資訊，每日自動更新至 Supabase 資料庫。

## 📋 功能

- 每日自動爬取最新賽程資訊
- 資料儲存於 Supabase 資料庫
- 使用 GitHub Actions 自動化執行

## 🛠️ 技術棧

- **Python 3.10**
- **Supabase** (PostgreSQL 資料庫)
- **GitHub Actions** (自動化排程)

## 📦 安裝與設定

### 1. Clone 專案
```bash
git clone https://github.com/你的帳號/你的專案名稱.git
cd 你的專案名稱
```

### 2. 安裝套件
```bash
pip install -r requirements.txt
```

### 3. 設定環境變數

建立 `.env` 檔案:
```env
SUPABASE_HOST=your_host.supabase.co
SUPABASE_DATABASE=postgres
SUPABASE_USER=postgres
SUPABASE_PASSWORD=your_password
SUPABASE_PORT=5432
```

### 4. 本地測試
```bash
python scraper.py
```

## ⚙️ GitHub Actions 設定

### 設定 Secrets

在 GitHub Repository 中設定以下 Secrets:

1. 進入 **Settings** → **Secrets and variables** → **Actions**
2. 新增以下 secrets:
   - `SUPABASE_HOST`
   - `SUPABASE_DATABASE`
   - `SUPABASE_USER`
   - `SUPABASE_PASSWORD`
   - `SUPABASE_PORT`

### 自動執行時間

- 每天台灣時間 **10:00** 自動執行
- 也可以在 Actions 頁面手動觸發

## 📁 專案結構
```
.
├── .github/
│   └── workflows/
│       └── scraper.yml      # GitHub Actions 設定
├── .gitignore               # Git 忽略檔案
├── requirements.txt         # Python 套件清單
├── scraper.py              # 爬蟲主程式
├── .env                    # 環境變數 (不上傳)
└── README.md               # 專案說明
```

## 📝 使用的套件

- `psycopg2-binary` - PostgreSQL 資料庫連線
- `python-dotenv` - 環境變數管理
- `requests` - HTTP 請求

## 📌 注意事項

- `.env` 檔案包含敏感資訊，**不要上傳到 GitHub**
- 確保 Supabase 資料庫連線資訊正確
- GitHub Actions 需要設定所有必要的 Secrets

## 👩‍💻 開發者

開發者: Amy  
National Taiwan Normal University

## 📄 授權

MIT License

---

**🎯 專案目標**: 為排球愛好者提供即時、準確的賽程資訊