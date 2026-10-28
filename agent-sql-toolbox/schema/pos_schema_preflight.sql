/*
AgentChat/coding_agent 2026-07-08T20:31:00Z
Purpose: read-only schema compatibility check for Agent SQL Toolbox scripts.
Run this in the target POS_<Company_Username__c> database before using toolbox reports
or migration templates.
*/

SET NOCOUNT ON;

DECLARE @RequiredColumns TABLE (
    SchemaName SYSNAME NOT NULL DEFAULT N'dbo',
    TableName SYSNAME NOT NULL,
    ColumnName SYSNAME NOT NULL,
    UsedBy NVARCHAR(200) NOT NULL
);

INSERT INTO @RequiredColumns (TableName, ColumnName, UsedBy)
VALUES
    (N'Appointments', N'Id', N'reports/appointment_duration.sql'),
    (N'Appointments', N'Start', N'reports/appointment_duration.sql'),
    (N'Appointments', N'End', N'reports/appointment_duration.sql'),
    (N'Appointments', N'CustomerID', N'reports/appointment_duration.sql'),
    (N'Appointments', N'EmployeeID', N'reports/appointment_duration.sql'),
    (N'Appointments', N'LocationID', N'reports/appointment_duration.sql'),
    (N'Appointments', N'Description', N'reports/appointment_duration.sql'),
    (N'Customers', N'CustomerID', N'reports/customer_purchase_detail.sql'),
    (N'Customers', N'CustomerFirstName', N'reports/customer_purchase_detail.sql'),
    (N'Customers', N'CustomerLastName', N'reports/customer_purchase_detail.sql'),
    (N'Customers', N'CustomerLandLine', N'reports/customer_purchase_detail.sql'),
    (N'Customers', N'CustomerMobile', N'reports/customer_purchase_detail.sql'),
    (N'Customers', N'CustomerEmail', N'reports/customer_purchase_detail.sql'),
    (N'Customers', N'DateAdded', N'reports/customer_purchase_detail.sql'),
    (N'Employees', N'EmployeeID', N'reports/customer_purchase_detail.sql; reports/employee_commission_summary.sql'),
    (N'Employees', N'EmployeeName', N'reports/customer_purchase_detail.sql; reports/employee_commission_summary.sql'),
    (N'Employees_Deductions', N'EmployeeID', N'reports/employee_commission_summary.sql'),
    (N'Employees_Deductions', N'LocationID', N'reports/employee_commission_summary.sql'),
    (N'Employees_Deductions', N'Timestamp', N'reports/employee_commission_summary.sql'),
    (N'Employees_Deductions', N'Amount', N'reports/employee_commission_summary.sql'),
    (N'Employees_Hours', N'EmployeeID', N'reports/employee_commission_summary.sql'),
    (N'Employees_Hours', N'LocationID', N'reports/employee_commission_summary.sql'),
    (N'Employees_Hours', N'Date', N'reports/employee_commission_summary.sql'),
    (N'Employees_Hours', N'Hours', N'reports/employee_commission_summary.sql'),
    (N'Employees_Reimbursements', N'EmployeeID', N'reports/employee_commission_summary.sql'),
    (N'Employees_Reimbursements', N'LocationID', N'reports/employee_commission_summary.sql'),
    (N'Employees_Reimbursements', N'Timestamp', N'reports/employee_commission_summary.sql'),
    (N'Employees_Reimbursements', N'Amount', N'reports/employee_commission_summary.sql'),
    (N'Inventory', N'LocationID', N'reports/inventory_by_location.sql; migration/copy_products_template.sql'),
    (N'Inventory', N'ProductID', N'reports/inventory_by_location.sql; migration/copy_products_template.sql'),
    (N'Inventory', N'Quantity', N'reports/inventory_by_location.sql; migration/copy_products_template.sql'),
    (N'Inventory', N'DesiredQuantity', N'reports/inventory_by_location.sql; migration/copy_products_template.sql'),
    (N'Inventory', N'MinimumQuantity', N'reports/inventory_by_location.sql; migration/copy_products_template.sql'),
    (N'Inventory_Counts', N'InventoryCountID', N'reports/inventory_count_detail.sql'),
    (N'Inventory_Counts', N'LocationID', N'reports/inventory_count_detail.sql'),
    (N'Inventory_Counts', N'EmployeeID', N'reports/inventory_count_detail.sql'),
    (N'Inventory_Counts', N'Timestamp', N'reports/inventory_count_detail.sql'),
    (N'Inventory_Counts', N'Status', N'reports/inventory_count_detail.sql'),
    (N'Inventory_Counts_Products', N'InventoryCountID', N'reports/inventory_count_detail.sql'),
    (N'Inventory_Counts_Products', N'ProductID', N'reports/inventory_count_detail.sql'),
    (N'Inventory_Counts_Products', N'Count', N'reports/inventory_count_detail.sql'),
    (N'Invoice_Employees', N'InvoiceID', N'reports/customer_purchase_detail.sql; reports/employee_commission_summary.sql'),
    (N'Invoice_Employees', N'EmployeeID', N'reports/customer_purchase_detail.sql; reports/employee_commission_summary.sql'),
    (N'Invoice_Employees', N'AmountForComission', N'reports/customer_purchase_detail.sql; reports/employee_commission_summary.sql'),
    (N'Invoice_Employees', N'AmountForComissionTimestamp', N'reports/employee_commission_summary.sql'),
    (N'Invoice_Payments', N'InvoiceID', N'reports/customer_purchase_detail.sql'),
    (N'Invoice_Payments', N'PaymentMethod', N'reports/customer_purchase_detail.sql'),
    (N'Invoice_Payments', N'PaymentDetails', N'reports/customer_purchase_detail.sql'),
    (N'Invoice_Payments', N'Amount', N'reports/customer_purchase_detail.sql'),
    (N'Invoice_Products', N'InvoiceID', N'reports/customer_purchase_detail.sql'),
    (N'Invoice_Products', N'ProductID', N'reports/customer_purchase_detail.sql'),
    (N'Invoice_Products', N'Quantity', N'reports/customer_purchase_detail.sql'),
    (N'Invoice_Products', N'ProductPrice', N'reports/customer_purchase_detail.sql'),
    (N'Invoice_Products', N'ProductDiscount', N'reports/customer_purchase_detail.sql'),
    (N'Invoice_Products', N'ProductTax', N'reports/customer_purchase_detail.sql'),
    (N'Invoices', N'InvoiceID', N'reports/customer_purchase_detail.sql; reports/employee_commission_summary.sql'),
    (N'Invoices', N'Timestamp', N'reports/customer_purchase_detail.sql; reports/employee_commission_summary.sql'),
    (N'Invoices', N'CustomerID', N'reports/customer_purchase_detail.sql'),
    (N'Invoices', N'LocationID', N'reports/customer_purchase_detail.sql; reports/employee_commission_summary.sql'),
    (N'Invoices', N'Total', N'reports/customer_purchase_detail.sql'),
    (N'Locations', N'LocationID', N'reports/*; migration/copy_location_settings_template.sql'),
    (N'Locations', N'LocationName', N'reports/*; migration/copy_location_settings_template.sql'),
    (N'Locations', N'RegionID', N'reports/customer_purchase_detail.sql'),
    (N'Products', N'ProductID', N'reports/*; migration/copy_products_template.sql'),
    (N'Products', N'ProductName', N'reports/*; migration/copy_products_template.sql'),
    (N'Products', N'ProductDescription', N'reports/*; migration/copy_products_template.sql'),
    (N'Products', N'ProductIsAvailable', N'reports/*; migration/copy_products_template.sql'),
    (N'Products', N'BarcodeNumber', N'reports/*; migration/copy_products_template.sql'),
    (N'Products', N'BarcodeNumber2', N'reports/*; migration/copy_products_template.sql'),
    (N'Products', N'SKU', N'reports/*; migration/copy_products_template.sql'),
    (N'Products', N'Product_CategoryID', N'reports/inventory_by_location.sql; migration/copy_products_template.sql'),
    (N'Products', N'WholesalerID', N'reports/inventory_by_location.sql; migration/copy_products_template.sql'),
    (N'Products_Categories', N'Products_CategoryID', N'reports/inventory_by_location.sql; migration/copy_products_template.sql'),
    (N'Products_Categories', N'Products_CategoryName', N'reports/inventory_by_location.sql; migration/copy_products_template.sql'),
    (N'Products_Categories', N'ParentID', N'reports/inventory_by_location.sql'),
    (N'Products_Wholesalers', N'WholesalerID', N'reports/inventory_by_location.sql; migration/copy_products_template.sql'),
    (N'Products_Wholesalers', N'WholesalerName', N'reports/inventory_by_location.sql; migration/copy_products_template.sql'),
    (N'Regions', N'RegionID', N'reports/customer_purchase_detail.sql'),
    (N'Regions', N'RegionName', N'reports/customer_purchase_detail.sql');

;WITH Missing AS (
    SELECT
        required.SchemaName,
        required.TableName,
        required.ColumnName,
        required.UsedBy,
        MissingReason =
            CASE
                WHEN objectInfo.object_id IS NULL THEN 'MISSING_TABLE'
                WHEN columnInfo.column_id IS NULL THEN 'MISSING_COLUMN'
                ELSE 'OK'
            END
    FROM @RequiredColumns AS required
    LEFT JOIN sys.objects AS objectInfo
      ON objectInfo.object_id = OBJECT_ID(QUOTENAME(required.SchemaName) + N'.' + QUOTENAME(required.TableName))
     AND objectInfo.type = 'U'
    LEFT JOIN sys.columns AS columnInfo
      ON columnInfo.object_id = objectInfo.object_id
     AND columnInfo.name = required.ColumnName
)
SELECT
    DB_NAME() AS DatabaseName,
    SchemaName,
    TableName,
    ColumnName,
    UsedBy,
    MissingReason
FROM Missing
WHERE MissingReason <> 'OK'
ORDER BY TableName, ColumnName;

IF NOT EXISTS (
    SELECT 1
    FROM @RequiredColumns AS required
    LEFT JOIN sys.objects AS objectInfo
      ON objectInfo.object_id = OBJECT_ID(QUOTENAME(required.SchemaName) + N'.' + QUOTENAME(required.TableName))
     AND objectInfo.type = 'U'
    LEFT JOIN sys.columns AS columnInfo
      ON columnInfo.object_id = objectInfo.object_id
     AND columnInfo.name = required.ColumnName
    WHERE objectInfo.object_id IS NULL OR columnInfo.column_id IS NULL
)
BEGIN
    SELECT DB_NAME() AS DatabaseName, 'SCHEMA_COMPATIBLE' AS ToolboxSchemaStatus;
END
ELSE
BEGIN
    SELECT DB_NAME() AS DatabaseName, 'SCHEMA_MISMATCH_REVIEW_BEFORE_USE' AS ToolboxSchemaStatus;
END;
