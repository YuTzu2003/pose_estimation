CREATE TABLE [dbo].[Session] (
    [Session_id]      VARCHAR(50)    NOT NULL,                  --場次id
    [Session_name]    NVARCHAR(200)  NOT NULL,                  --場次名稱
    [Player_id]       VARCHAR(20)    NOT NULL,                  --使用者選手id
    [Note]            NVARCHAR(MAX)  NULL,                      --備註
    [Project_Folder]  NVARCHAR(500)  NOT NULL,                  --專案資料夾路徑
    [Created_at]      DATETIME       NOT NULL DEFAULT GETDATE()
);


CREATE TABLE [dbo].[Record] (
    [Record_id]        VARCHAR(20)    NOT NULL,                  --影片紀錄id
    [Session_id]       VARCHAR(50)    NOT NULL,                  --場次id
    [Project_Folder]   NVARCHAR(500)  NOT NULL,                  --專案影片資料夾路徑
    [Frame_Start]      SMALLINT       NOT NULL,                  --出現人起始frame
    [Frame_End]        SMALLINT       NOT NULL,                  --出現人最後frame
    [Scale_Reference]  FLOAT          NOT NULL,                  --比例尺(真實值)
    [Scale_Pixels]     FLOAT          NOT NULL                   --圖片像素
);


CREATE TABLE [dbo].[Player] (
    [Player_id]    VARCHAR(20)    NOT NULL,
    [Name]         NVARCHAR(100)  NOT NULL,
    [Gender]       NVARCHAR(10)   NOT NULL,
    [BirthDate]    DATE           NOT NULL,
    [Height]       FLOAT          NULL,
    [Weight]       FLOAT          NULL,
    [Sport]        NVARCHAR(100)  NOT NULL,
    [Created_at]   DATETIME       NOT NULL
);