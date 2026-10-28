import sys
sys.path.insert(0, "tools/scoped-operations-mcp/src")
from scoped_operations_mcp.salesforce_client import SalesforceSettings, ScopedSalesforceClient
from scoped_operations_mcp.nova_sql_client import ScopedNovaSqlClient, NovaSqlSettings

sf = ScopedSalesforceClient(SalesforceSettings.from_environment())
ns = ScopedNovaSqlClient(salesforce_client=sf, settings=NovaSqlSettings(), write_enabled=False)

def one(q):
    r = ns.read("Valiant", q, max_rows=10)
    return r.get("rows", [{}])[0]

print("LOC4 total inventory rows:", one("SELECT COUNT(*) AS n FROM Inventory WHERE LocationID=4").get("n"))
print("LOC4 rows with stock:    ", one("SELECT COUNT(*) AS n FROM Inventory WHERE LocationID=4 AND Quantity>0").get("n"))
print("LOC4 total units:        ", one("SELECT SUM(Quantity) AS n FROM Inventory WHERE LocationID=4 AND Quantity>0").get("n"))
print("LOC7 total inventory rows:", one("SELECT COUNT(*) AS n FROM Inventory WHERE LocationID=7").get("n"))
print("LOC7 rows with stock:    ", one("SELECT COUNT(*) AS n FROM Inventory WHERE LocationID=7 AND Quantity>0").get("n"))
print("LOC7 total units:        ", one("SELECT SUM(Quantity) AS n FROM Inventory WHERE LocationID=7 AND Quantity>0").get("n"))
print("LOC4 products NOT in LOC7:", one("SELECT COUNT(*) AS n FROM Inventory i4 WHERE i4.LocationID=4 AND NOT EXISTS (SELECT 1 FROM Inventory i7 WHERE i7.LocationID=7 AND i7.ProductID=i4.ProductID)").get("n"))