/*
AgentChat/coding_agent 2026-07-08T20:31:00Z
Source: generalized from "Reindex Account.sql" and customer-specific reindex scripts.
Purpose: generate index maintenance commands for the current POS database.
Default: dry run. Execution requires @Execute = 1 and an exact confirmation phrase.
*/

SET NOCOUNT ON;

DECLARE @MinPageCount INT = 1000;
DECLARE @ReorganizeAtFragmentationPercent DECIMAL(5,2) = 5.0;
DECLARE @RebuildAtFragmentationPercent DECIMAL(5,2) = 30.0;
DECLARE @FillFactor INT = 80;
DECLARE @Execute BIT = 0;
DECLARE @ConfirmExecutionPhrase NVARCHAR(80) = N''; -- must equal: EXECUTE INDEX MAINTENANCE

IF @FillFactor NOT BETWEEN 0 AND 100
BEGIN
    THROW 51000, '@FillFactor must be between 0 and 100.', 1;
END;

IF OBJECT_ID('tempdb..#IndexWork') IS NOT NULL DROP TABLE #IndexWork;

SELECT
    SchemaName = schemaInfo.name,
    TableName = tableInfo.name,
    IndexName = indexInfo.name,
    stats.avg_fragmentation_in_percent,
    stats.page_count,
    CommandText =
        CASE
            WHEN stats.avg_fragmentation_in_percent >= @RebuildAtFragmentationPercent THEN
                N'ALTER INDEX ' + QUOTENAME(indexInfo.name) + N' ON '
                + QUOTENAME(schemaInfo.name) + N'.' + QUOTENAME(tableInfo.name)
                + N' REBUILD WITH (SORT_IN_TEMPDB = ON, ONLINE = OFF'
                + CASE WHEN @FillFactor > 0 THEN N', FILLFACTOR = ' + CONVERT(NVARCHAR(10), @FillFactor) ELSE N'' END
                + N');'
            WHEN stats.avg_fragmentation_in_percent >= @ReorganizeAtFragmentationPercent THEN
                N'ALTER INDEX ' + QUOTENAME(indexInfo.name) + N' ON '
                + QUOTENAME(schemaInfo.name) + N'.' + QUOTENAME(tableInfo.name)
                + N' REORGANIZE;'
        END
INTO #IndexWork
FROM sys.dm_db_index_physical_stats(DB_ID(), NULL, NULL, NULL, 'LIMITED') AS stats
JOIN sys.indexes AS indexInfo
    ON indexInfo.object_id = stats.object_id
   AND indexInfo.index_id = stats.index_id
JOIN sys.tables AS tableInfo ON tableInfo.object_id = stats.object_id
JOIN sys.schemas AS schemaInfo ON schemaInfo.schema_id = tableInfo.schema_id
WHERE stats.database_id = DB_ID()
  AND stats.index_id > 0
  AND indexInfo.name IS NOT NULL
  AND tableInfo.is_ms_shipped = 0
  AND stats.page_count >= @MinPageCount
  AND stats.avg_fragmentation_in_percent >= @ReorganizeAtFragmentationPercent;

SELECT
    DB_NAME() AS DatabaseName,
    SchemaName,
    TableName,
    IndexName,
    avg_fragmentation_in_percent,
    page_count,
    CommandText,
    CASE WHEN @Execute = 1 THEN 'WILL_EXECUTE' ELSE 'DRY_RUN_ONLY' END AS ExecutionMode
FROM #IndexWork
ORDER BY avg_fragmentation_in_percent DESC, page_count DESC;

IF @Execute = 1 AND @ConfirmExecutionPhrase <> N'EXECUTE INDEX MAINTENANCE'
BEGIN
    THROW 51001, 'Execution blocked. Set @ConfirmExecutionPhrase = N''EXECUTE INDEX MAINTENANCE'' after explicit authorization.', 1;
END;

IF @Execute = 1
BEGIN
    DECLARE @CommandText NVARCHAR(MAX);
    DECLARE commandCursor CURSOR LOCAL FAST_FORWARD FOR
        SELECT CommandText
        FROM #IndexWork
        WHERE CommandText IS NOT NULL
        ORDER BY avg_fragmentation_in_percent DESC, page_count DESC;

    OPEN commandCursor;
    FETCH NEXT FROM commandCursor INTO @CommandText;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        PRINT @CommandText;
        EXEC sys.sp_executesql @CommandText;
        FETCH NEXT FROM commandCursor INTO @CommandText;
    END;
    CLOSE commandCursor;
    DEALLOCATE commandCursor;
END;
