/*
AgentChat/coding_agent 2026-07-08T20:31:00Z
Source: generalized from "Copy location settings.sql" and "CopyLocations.sql".
Purpose: copy non-secret operational location settings from a source account/location
to the current target database/location.
Default: dry run. If @Execute = 1 without @CommitChanges = 1 and the commit
phrase, the transaction is rolled back.
*/

SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @SourceDB SYSNAME = N'POS_SOURCE_ACCOUNT';
DECLARE @SourceLocationID INT = NULL;
DECLARE @TargetLocationID INT = NULL;
DECLARE @Execute BIT = 0;
DECLARE @CommitChanges BIT = 0;
DECLARE @ConfirmCommitPhrase NVARCHAR(80) = N''; -- must equal: COMMIT LOCATION SETTINGS COPY

IF DB_ID(@SourceDB) IS NULL
BEGIN
    THROW 51000, 'Source database was not found on this SQL Server.', 1;
END;

IF @SourceLocationID IS NULL OR @TargetLocationID IS NULL
BEGIN
    THROW 51000, 'Set @SourceLocationID and @TargetLocationID before running.', 1;
END;

DECLARE @Sql NVARCHAR(MAX) = N'
SELECT
    ExecutionMode = CASE WHEN @Execute = 1 THEN ''WILL_UPDATE'' ELSE ''DRY_RUN_ONLY'' END,
    SourceDB = @SourceDB,
    SourceLocationID = src.LocationID,
    SourceLocationName = src.LocationName,
    TargetDB = DB_NAME(),
    TargetLocationID = tgt.LocationID,
    TargetLocationName = tgt.LocationName,
    src.LocationTaxRate,
    tgt.LocationTaxRate AS CurrentTargetTaxRate,
    src.LocationSecondTaxRate,
    tgt.LocationSecondTaxRate AS CurrentTargetSecondTaxRate,
    src.TextOnInvoice,
    tgt.TextOnInvoice AS CurrentTargetTextOnInvoice,
    src.HeaderTextOnInvoice,
    tgt.HeaderTextOnInvoice AS CurrentTargetHeaderTextOnInvoice
FROM ' + QUOTENAME(@SourceDB) + N'.dbo.Locations AS src
CROSS JOIN dbo.Locations AS tgt
WHERE src.LocationID = @SourceLocationID
  AND tgt.LocationID = @TargetLocationID;';

EXEC sys.sp_executesql
    @Sql,
    N'@SourceDB SYSNAME, @SourceLocationID INT, @TargetLocationID INT, @Execute BIT',
    @SourceDB = @SourceDB,
    @SourceLocationID = @SourceLocationID,
    @TargetLocationID = @TargetLocationID,
    @Execute = @Execute;

IF @Execute = 1
BEGIN
    IF @CommitChanges = 1 AND @ConfirmCommitPhrase <> N'COMMIT LOCATION SETTINGS COPY'
    BEGIN
        THROW 51001, 'Commit blocked. Set @ConfirmCommitPhrase = N''COMMIT LOCATION SETTINGS COPY'' after explicit authorization.', 1;
    END;

    SET @Sql = N'
    UPDATE tgt
       SET LocationTaxRate = src.LocationTaxRate,
           LocationSecondTaxRate = src.LocationSecondTaxRate,
           LocationSecondTaxRateName = src.LocationSecondTaxRateName,
           TextOnInvoice = src.TextOnInvoice,
           HeaderTextOnInvoice = src.HeaderTextOnInvoice,
           IsForceMinimumPrice = src.IsForceMinimumPrice,
           MaxMinutesSinceLastInvoiceToAttach = src.MaxMinutesSinceLastInvoiceToAttach,
           ShowListInsteadOfButtons = src.ShowListInsteadOfButtons,
           IsHideProductPricesOnInvoice = src.IsHideProductPricesOnInvoice,
           IsBlockCashDrawer = src.IsBlockCashDrawer,
           IsForceInventoryCount = src.IsForceInventoryCount,
           IsBlockSaleIfProductQuantityZero = src.IsBlockSaleIfProductQuantityZero,
           IsAllowSaleWithNoEmployees = src.IsAllowSaleWithNoEmployees,
           IsAskForCustomerInfoInEverySale = src.IsAskForCustomerInfoInEverySale,
           IsBlockEmployeeReports = src.IsBlockEmployeeReports,
           IsDisplayProductPriceIncTax = src.IsDisplayProductPriceIncTax,
           AltTaxName = src.AltTaxName,
           IsAltTaxName = src.IsAltTaxName,
           DefaultStoreCreditExpDays = src.DefaultStoreCreditExpDays,
           IsHideEndOfDayReport = src.IsHideEndOfDayReport,
           IsEnableCashCount = src.IsEnableCashCount,
           IsHideDiscountFromCustomer = src.IsHideDiscountFromCustomer,
           AllowCheckAsPayment = src.AllowCheckAsPayment,
           BlockOtherLocationsInvoices = src.BlockOtherLocationsInvoices,
           IsPrintMasterZ = src.IsPrintMasterZ,
           IsAllowManualCCEntry = src.IsAllowManualCCEntry,
           IsForceCVV = src.IsForceCVV,
           IsLimitGiftCardToRegion = src.IsLimitGiftCardToRegion,
           IsAllowTipsActive = src.IsAllowTipsActive,
           PercentageTipAmount = src.PercentageTipAmount,
           CompetitionScopeEnum = src.CompetitionScopeEnum,
           HideInventoryChangesFromEndOfDayReport = src.HideInventoryChangesFromEndOfDayReport,
           TimezoneID = src.TimezoneID,
           AllowInstallments = src.AllowInstallments,
           MinimunAmountAllowInstallments = src.MinimunAmountAllowInstallments,
           MaximunInstallmentsAllowed = src.MaximunInstallmentsAllowed,
           ForceDigitalSignatureInstallments = src.ForceDigitalSignatureInstallments,
           EnforceCustomerInfoCollection = src.EnforceCustomerInfoCollection,
           AllEmployeesAppointment = src.AllEmployeesAppointment
    FROM dbo.Locations AS tgt
    JOIN ' + QUOTENAME(@SourceDB) + N'.dbo.Locations AS src
      ON src.LocationID = @SourceLocationID
    WHERE tgt.LocationID = @TargetLocationID;';

    BEGIN TRY
        BEGIN TRAN;
        EXEC sys.sp_executesql
            @Sql,
            N'@SourceLocationID INT, @TargetLocationID INT',
            @SourceLocationID = @SourceLocationID,
            @TargetLocationID = @TargetLocationID;
        SELECT @@ROWCOUNT AS UpdatedLocationRows;

        IF @CommitChanges = 1
        BEGIN
            COMMIT TRAN;
            SELECT 'COMMITTED' AS TransactionStatus;
        END
        ELSE
        BEGIN
            ROLLBACK TRAN;
            SELECT 'ROLLED_BACK_PREVIEW_ONLY' AS TransactionStatus;
        END;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0
        BEGIN
            ROLLBACK TRAN;
        END;
        THROW;
    END CATCH;
END;
