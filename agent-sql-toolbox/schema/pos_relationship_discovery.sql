/*
AgentChat/coding_agent 2026-07-09
Purpose: read-only relationship discovery for Nova POS databases.
Run in the target POS_<Company_Username__c> database after pos_schema_preflight.sql.

This script reads SQL Server catalog views only. It does not inspect customer
rows and does not modify database data.
*/

SET NOCOUNT ON;

DECLARE @ShowCoreColumns BIT = 1;
DECLARE @ShowInferredIdColumns BIT = 1;

DECLARE @CoreTables TABLE (
    Domain NVARCHAR(80) NOT NULL,
    TableName SYSNAME NOT NULL,
    SupportUse NVARCHAR(300) NOT NULL,
    PRIMARY KEY (TableName)
);

INSERT INTO @CoreTables (Domain, TableName, SupportUse)
VALUES
    (N'Account/location', N'Regions', N'Region grouping for locations and reports'),
    (N'Account/location', N'Locations', N'Location-scoped sales, inventory, appointments, salary windows'),
    (N'Customers', N'Customers', N'Customer profile attached to invoice headers and appointments'),
    (N'Sales', N'Invoices', N'Sale/refund/layaway header and customer/location link'),
    (N'Sales', N'Invoice_Products', N'Products sold on an invoice'),
    (N'Sales', N'Invoice_Payments', N'Payment rows for an invoice'),
    (N'Sales', N'Invoice_Employees', N'Commission attribution for an invoice'),
    (N'Products', N'Products', N'Sellable product catalog'),
    (N'Products', N'Products_Categories', N'Product categories and parent categories'),
    (N'Products', N'Products_Wholesalers', N'Product wholesaler/vendor names'),
    (N'Inventory', N'Inventory', N'Location-specific product quantity'),
    (N'Inventory', N'Inventory_Counts', N'Inventory count header'),
    (N'Inventory', N'Inventory_Counts_Products', N'Inventory count detail lines'),
    (N'Employees', N'Employees', N'Users/employees for sales, appointments, salary'),
    (N'Employees', N'Employees_Hours', N'Hours worked by employee/location'),
    (N'Employees', N'Employees_Reimbursements', N'Reimbursements by employee/location'),
    (N'Employees', N'Employees_Deductions', N'Deductions by employee/location'),
    (N'Appointments', N'Appointments', N'Appointment schedule rows'),
    (N'Refunds', N'Refunds', N'Refund header linked to invoice when present'),
    (N'Refunds', N'Refunds_Products', N'Refund product detail rows when present'),
    (N'Refunds', N'Refunds_Payments', N'Refund payment detail rows when present'),
    (N'Layaway', N'Customer_Orders', N'Layaway/customer order header when present');

DECLARE @RelationshipMap TABLE (
    Domain NVARCHAR(80) NOT NULL,
    ParentTable SYSNAME NOT NULL,
    ParentColumn SYSNAME NOT NULL,
    ChildTable SYSNAME NOT NULL,
    ChildColumn SYSNAME NOT NULL,
    RelationshipName NVARCHAR(160) NOT NULL,
    SupportUse NVARCHAR(300) NOT NULL
);

INSERT INTO @RelationshipMap
    (Domain, ParentTable, ParentColumn, ChildTable, ChildColumn, RelationshipName, SupportUse)
VALUES
    (N'Account/location', N'Regions', N'RegionID', N'Locations', N'RegionID', N'Location belongs to region', N'Region/location report filtering'),
    (N'Sales', N'Customers', N'CustomerID', N'Invoices', N'CustomerID', N'Invoice belongs to customer', N'Customer sale history and invoice customer attachment'),
    (N'Sales', N'Locations', N'LocationID', N'Invoices', N'LocationID', N'Invoice belongs to location', N'Location-scoped reports and receipts'),
    (N'Sales', N'Invoices', N'InvoiceID', N'Invoice_Products', N'InvoiceID', N'Invoice product detail', N'Invoice product rows'),
    (N'Sales', N'Products', N'ProductID', N'Invoice_Products', N'ProductID', N'Invoice product catalog link', N'Product sold on invoice'),
    (N'Sales', N'Invoices', N'InvoiceID', N'Invoice_Payments', N'InvoiceID', N'Invoice payment detail', N'Payment method/details'),
    (N'Sales', N'Invoices', N'InvoiceID', N'Invoice_Employees', N'InvoiceID', N'Invoice employee detail', N'Commission attribution'),
    (N'Sales', N'Employees', N'EmployeeID', N'Invoice_Employees', N'EmployeeID', N'Invoice employee user link', N'Commission employee name'),
    (N'Products', N'Products_Categories', N'Products_CategoryID', N'Products', N'Product_CategoryID', N'Product category', N'Product filtering and sale screen visibility'),
    (N'Products', N'Products_Categories', N'Products_CategoryID', N'Products_Categories', N'ParentID', N'Category parent', N'Parent/child category navigation'),
    (N'Products', N'Products_Wholesalers', N'WholesalerID', N'Products', N'WholesalerID', N'Product wholesaler', N'Inventory and product reports'),
    (N'Inventory', N'Products', N'ProductID', N'Inventory', N'ProductID', N'Inventory product', N'Location quantity by product'),
    (N'Inventory', N'Locations', N'LocationID', N'Inventory', N'LocationID', N'Inventory location', N'Location quantity by product'),
    (N'Inventory', N'Locations', N'LocationID', N'Inventory_Counts', N'LocationID', N'Inventory count location', N'Inventory count report location'),
    (N'Inventory', N'Employees', N'EmployeeID', N'Inventory_Counts', N'EmployeeID', N'Inventory count submitter', N'Inventory count employee'),
    (N'Inventory', N'Inventory_Counts', N'InventoryCountID', N'Inventory_Counts_Products', N'InventoryCountID', N'Inventory count detail', N'Inventory counted products'),
    (N'Inventory', N'Products', N'ProductID', N'Inventory_Counts_Products', N'ProductID', N'Inventory count product', N'Inventory counted product catalog link'),
    (N'Employees', N'Employees', N'EmployeeID', N'Employees_Hours', N'EmployeeID', N'Hours employee', N'Salary hours'),
    (N'Employees', N'Locations', N'LocationID', N'Employees_Hours', N'LocationID', N'Hours location', N'Salary hours by location'),
    (N'Employees', N'Employees', N'EmployeeID', N'Employees_Reimbursements', N'EmployeeID', N'Reimbursement employee', N'Salary reimbursement'),
    (N'Employees', N'Locations', N'LocationID', N'Employees_Reimbursements', N'LocationID', N'Reimbursement location', N'Salary reimbursement by location'),
    (N'Employees', N'Employees', N'EmployeeID', N'Employees_Deductions', N'EmployeeID', N'Deduction employee', N'Salary deduction'),
    (N'Employees', N'Locations', N'LocationID', N'Employees_Deductions', N'LocationID', N'Deduction location', N'Salary deduction by location'),
    (N'Appointments', N'Customers', N'CustomerID', N'Appointments', N'CustomerID', N'Appointment customer', N'Appointment customer details'),
    (N'Appointments', N'Employees', N'EmployeeID', N'Appointments', N'EmployeeID', N'Appointment employee', N'Appointment employee details'),
    (N'Appointments', N'Locations', N'LocationID', N'Appointments', N'LocationID', N'Appointment location', N'Appointment location filtering'),
    (N'Refunds', N'Invoices', N'InvoiceID', N'Refunds', N'InvoiceID', N'Refund invoice', N'Refund linked to original/negative invoice'),
    (N'Refunds', N'Refunds', N'RefundID', N'Refunds_Products', N'RefundID', N'Refund product detail', N'Refund product rows'),
    (N'Refunds', N'Products', N'ProductID', N'Refunds_Products', N'ProductID', N'Refund product catalog link', N'Refunded product'),
    (N'Refunds', N'Refunds', N'RefundID', N'Refunds_Payments', N'RefundID', N'Refund payment detail', N'Refund payment method/details'),
    (N'Layaway', N'Customers', N'CustomerID', N'Customer_Orders', N'CustomerID', N'Customer order customer', N'Layaway/customer order owner'),
    (N'Layaway', N'Invoices', N'InvoiceID', N'Customer_Orders', N'InvoiceID', N'Customer order invoice', N'Layaway invoice link when present');

SELECT
    DB_NAME() AS DatabaseName,
    SYSDATETIMEOFFSET() AS CheckedAt,
    N'Read-only catalog relationship discovery' AS CheckType;

SELECT
    core.Domain,
    core.TableName,
    TableStatus = CASE WHEN tableInfo.object_id IS NULL THEN N'MISSING' ELSE N'PRESENT' END,
    ApproxRows = COALESCE(SUM(CASE WHEN partitions.index_id IN (0, 1) THEN partitions.rows ELSE 0 END), 0),
    core.SupportUse
FROM @CoreTables AS core
LEFT JOIN sys.tables AS tableInfo
    ON tableInfo.schema_id = SCHEMA_ID(N'dbo')
   AND tableInfo.name = core.TableName
LEFT JOIN sys.partitions AS partitions
    ON partitions.object_id = tableInfo.object_id
GROUP BY core.Domain, core.TableName, tableInfo.object_id, core.SupportUse
ORDER BY core.Domain, core.TableName;

;WITH RelationshipStatus AS (
    SELECT
        rel.Domain,
        rel.RelationshipName,
        rel.ParentTable,
        rel.ParentColumn,
        rel.ChildTable,
        rel.ChildColumn,
        rel.SupportUse,
        parentObject.object_id AS ParentObjectID,
        parentColumn.column_id AS ParentColumnID,
        childObject.object_id AS ChildObjectID,
        childColumn.column_id AS ChildColumnID
    FROM @RelationshipMap AS rel
    LEFT JOIN sys.tables AS parentObject
        ON parentObject.schema_id = SCHEMA_ID(N'dbo')
       AND parentObject.name = rel.ParentTable
    LEFT JOIN sys.columns AS parentColumn
        ON parentColumn.object_id = parentObject.object_id
       AND parentColumn.name = rel.ParentColumn
    LEFT JOIN sys.tables AS childObject
        ON childObject.schema_id = SCHEMA_ID(N'dbo')
       AND childObject.name = rel.ChildTable
    LEFT JOIN sys.columns AS childColumn
        ON childColumn.object_id = childObject.object_id
       AND childColumn.name = rel.ChildColumn
)
SELECT
    rel.Domain,
    rel.RelationshipName,
    RelationshipStatus =
        CASE
            WHEN rel.ParentObjectID IS NULL THEN N'MISSING_PARENT_TABLE'
            WHEN rel.ParentColumnID IS NULL THEN N'MISSING_PARENT_COLUMN'
            WHEN rel.ChildObjectID IS NULL THEN N'MISSING_CHILD_TABLE'
            WHEN rel.ChildColumnID IS NULL THEN N'MISSING_CHILD_COLUMN'
            WHEN fkInfo.ForeignKeyName IS NOT NULL THEN N'DECLARED_FOREIGN_KEY'
            ELSE N'IMPLIED_BY_NOVA_CONVENTION'
        END,
    ParentObject = N'dbo.' + rel.ParentTable + N'.' + rel.ParentColumn,
    ChildObject = N'dbo.' + rel.ChildTable + N'.' + rel.ChildColumn,
    fkInfo.ForeignKeyName,
    ChildColumnIndexCoverage =
        CASE
            WHEN rel.ChildObjectID IS NULL OR rel.ChildColumnID IS NULL THEN N'N/A'
            WHEN indexInfo.IndexName IS NULL THEN N'NO_INDEX_FOUND'
            WHEN indexInfo.KeyOrdinal = 1 THEN N'LEADING_KEY_INDEXED'
            ELSE N'NONLEADING_INDEXED'
        END,
    indexInfo.IndexName AS ChildColumnIndexName,
    rel.SupportUse
FROM RelationshipStatus AS rel
OUTER APPLY (
    SELECT TOP (1)
        fk.name AS ForeignKeyName
    FROM sys.foreign_keys AS fk
    JOIN sys.foreign_key_columns AS fkc
        ON fkc.constraint_object_id = fk.object_id
    WHERE fk.parent_object_id = rel.ChildObjectID
      AND fk.referenced_object_id = rel.ParentObjectID
      AND fkc.parent_column_id = rel.ChildColumnID
      AND fkc.referenced_column_id = rel.ParentColumnID
    ORDER BY fk.name
) AS fkInfo
OUTER APPLY (
    SELECT TOP (1)
        idx.name AS IndexName,
        idxColumn.key_ordinal AS KeyOrdinal
    FROM sys.index_columns AS idxColumn
    JOIN sys.indexes AS idx
        ON idx.object_id = idxColumn.object_id
       AND idx.index_id = idxColumn.index_id
    WHERE idxColumn.object_id = rel.ChildObjectID
      AND idxColumn.column_id = rel.ChildColumnID
      AND idx.is_disabled = 0
      AND idx.is_hypothetical = 0
    ORDER BY
        CASE WHEN idxColumn.key_ordinal = 1 THEN 0 ELSE 1 END,
        idx.is_unique DESC,
        idx.name
) AS indexInfo
ORDER BY rel.Domain, rel.ChildTable, rel.ChildColumn, rel.ParentTable;

SELECT
    fk.name AS ForeignKeyName,
    ChildTable = OBJECT_SCHEMA_NAME(fk.parent_object_id) + N'.' + OBJECT_NAME(fk.parent_object_id),
    ChildColumns = STRING_AGG(parentColumn.name, N', ') WITHIN GROUP (ORDER BY fkc.constraint_column_id),
    ParentTable = OBJECT_SCHEMA_NAME(fk.referenced_object_id) + N'.' + OBJECT_NAME(fk.referenced_object_id),
    ParentColumns = STRING_AGG(referencedColumn.name, N', ') WITHIN GROUP (ORDER BY fkc.constraint_column_id),
    fk.is_disabled,
    fk.is_not_trusted
FROM sys.foreign_keys AS fk
JOIN sys.foreign_key_columns AS fkc
    ON fkc.constraint_object_id = fk.object_id
JOIN sys.columns AS parentColumn
    ON parentColumn.object_id = fkc.parent_object_id
   AND parentColumn.column_id = fkc.parent_column_id
JOIN sys.columns AS referencedColumn
    ON referencedColumn.object_id = fkc.referenced_object_id
   AND referencedColumn.column_id = fkc.referenced_column_id
GROUP BY fk.name, fk.parent_object_id, fk.referenced_object_id, fk.is_disabled, fk.is_not_trusted
ORDER BY ChildTable, fk.name;

IF @ShowCoreColumns = 1
BEGIN
    SELECT
        core.Domain,
        core.TableName,
        col.column_id AS ColumnOrdinal,
        col.name AS ColumnName,
        TypeName = typeInfo.name,
        col.max_length,
        col.precision,
        col.scale,
        col.is_nullable,
        col.is_identity
    FROM @CoreTables AS core
    JOIN sys.tables AS tableInfo
        ON tableInfo.schema_id = SCHEMA_ID(N'dbo')
       AND tableInfo.name = core.TableName
    JOIN sys.columns AS col
        ON col.object_id = tableInfo.object_id
    JOIN sys.types AS typeInfo
        ON typeInfo.user_type_id = col.user_type_id
    ORDER BY core.Domain, core.TableName, col.column_id;
END;

IF @ShowInferredIdColumns = 1
BEGIN
    ;WITH SingleColumnKeys AS (
        SELECT
            parentTable.name AS ParentTable,
            parentColumn.name AS ParentColumn,
            parentTable.object_id AS ParentObjectID
        FROM sys.tables AS parentTable
        JOIN sys.indexes AS idx
            ON idx.object_id = parentTable.object_id
           AND idx.is_primary_key = 1
        JOIN sys.index_columns AS idxColumn
            ON idxColumn.object_id = idx.object_id
           AND idxColumn.index_id = idx.index_id
        JOIN sys.columns AS parentColumn
            ON parentColumn.object_id = idxColumn.object_id
           AND parentColumn.column_id = idxColumn.column_id
        WHERE parentTable.schema_id = SCHEMA_ID(N'dbo')
          AND NOT EXISTS (
                SELECT 1
                FROM sys.index_columns AS secondColumn
                WHERE secondColumn.object_id = idx.object_id
                  AND secondColumn.index_id = idx.index_id
                  AND secondColumn.key_ordinal > 1
          )
    ),
    IdColumns AS (
        SELECT
            childTable.name AS ChildTable,
            childColumn.name AS ChildColumn,
            childTable.object_id AS ChildObjectID,
            childColumn.column_id AS ChildColumnID
        FROM sys.tables AS childTable
        JOIN sys.columns AS childColumn
            ON childColumn.object_id = childTable.object_id
        WHERE childTable.schema_id = SCHEMA_ID(N'dbo')
          AND childTable.is_ms_shipped = 0
          AND childColumn.name LIKE N'%ID'
    )
    SELECT TOP (500)
        CandidateStatus =
            CASE
                WHEN known.ChildTable IS NOT NULL THEN N'IN_CORE_MAP'
                ELSE N'INFERRED_REVIEW'
            END,
        ParentObject = N'dbo.' + keyInfo.ParentTable + N'.' + keyInfo.ParentColumn,
        ChildObject = N'dbo.' + idInfo.ChildTable + N'.' + idInfo.ChildColumn,
        IndexCoverage =
            CASE
                WHEN indexInfo.IndexName IS NULL THEN N'NO_INDEX_FOUND'
                WHEN indexInfo.KeyOrdinal = 1 THEN N'LEADING_KEY_INDEXED'
                ELSE N'NONLEADING_INDEXED'
            END,
        indexInfo.IndexName
    FROM IdColumns AS idInfo
    JOIN SingleColumnKeys AS keyInfo
        ON keyInfo.ParentColumn = idInfo.ChildColumn
       AND keyInfo.ParentObjectID <> idInfo.ChildObjectID
    LEFT JOIN @RelationshipMap AS known
        ON known.ChildTable = idInfo.ChildTable
       AND known.ChildColumn = idInfo.ChildColumn
       AND known.ParentTable = keyInfo.ParentTable
       AND known.ParentColumn = keyInfo.ParentColumn
    OUTER APPLY (
        SELECT TOP (1)
            idx.name AS IndexName,
            idxColumn.key_ordinal AS KeyOrdinal
        FROM sys.index_columns AS idxColumn
        JOIN sys.indexes AS idx
            ON idx.object_id = idxColumn.object_id
           AND idx.index_id = idxColumn.index_id
        WHERE idxColumn.object_id = idInfo.ChildObjectID
          AND idxColumn.column_id = idInfo.ChildColumnID
          AND idx.is_disabled = 0
          AND idx.is_hypothetical = 0
        ORDER BY
            CASE WHEN idxColumn.key_ordinal = 1 THEN 0 ELSE 1 END,
            idx.is_unique DESC,
            idx.name
    ) AS indexInfo
    ORDER BY CandidateStatus, idInfo.ChildTable, idInfo.ChildColumn, keyInfo.ParentTable;
END;
