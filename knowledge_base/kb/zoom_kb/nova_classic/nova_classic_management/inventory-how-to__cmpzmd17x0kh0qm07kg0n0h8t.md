# Inventory How To

Source: Zoom Knowledge Library browser export
KB ID: nuqfxytazjfiask9ei4dk19b
Article ID: cmpzmd17x0kh0qm07kg0n0h8t
Product lane: Nova Classic
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/nuqfxytazjfiask9ei4dk19b/articles/cmpzmd17x0kh0qm07kg0n0h8t
Updated: 06/04/2026, 10:57 AM

Nova Classic How-To: Inventory

Source pass: Nova WinForms source, NovaFAQ/NovaKB public articles, and section inventory scout.

Customer-Facing Navigation

From the Management Screen, click Inventory.

The manager Inventory menu includes:

Management
Inventory Report
Purchase Orders
Automatic Purchase Orders
Transfers
Daily Counts
History
View Changes
Updates Log
View Testers and Losses
Testers/Losses Log
Manual Counts
Inventory > Management

Use Inventory > Management to select a location and open the location inventory screen.

Steps:

From the Management Screen, click Inventory.
Click Management.
Select the location.
Click Load Inventory.

Visible fields:

Inventory Management
Please select a location to manage its inventory
Load Inventory
Inventory Management Tabs

The location inventory screen has these tabs:

View Inventory By Item
View Inventory By Category
Update Inventory
Report Tester/Damage/Loss
Receive Inventory Transfer
Count Inventory By Item

Use View Inventory By Item to count product quantities one item at a time.

Steps:

Open Inventory > Management and load the location.
Open View Inventory By Item.
Enter the counted quantity in Count for each product.
Review Count Status if visible.
Click Submit Count.
Print the inventory if needed.

Columns:

Category
Barcode
Product Name
Desc.
Size
Color
Quantity
Full Capacity
Min Capacity
Count
Count Status
Remove Product

Actions:

Submit Count
print inventory
Count Inventory By Category

Use View Inventory By Category to submit counts grouped by category.

Steps:

Load the location inventory.
Open View Inventory By Category.
Enter the count for each category.
Click Submit Count.

Columns:

Category ID
Category
Quantity
Count
Count Status
Update Inventory

Use Update Inventory to add, remove, copy, or transfer inventory quantities.

Steps:

Load the location inventory.
Open Update Inventory.
Choose the view filters:
Show inactive products
Show products that are not in the inventory at this location
Show products in the inventory at this location
Choose the action/mode:
Add from
Add / Remove Products
Send to
Remove from inventory
Enter quantities in Quantity To Add/Remove.
Add Comments when helpful.
Click Update Inventory.

Other controls:

Copy capacities from
Copy
Add/Remove All
Comments

Common columns:

Active?
Barcode
Category
Product Name
Current Quantity
Quantity To Add/Remove
MinimumQuantity
IsSerialNumbers
IsComments
WholesalerID
Report Tester, Damage, Or Loss

Use Report Tester/Damage/Loss when inventory leaves sellable stock because it is damaged, lost, used as a tester, or for another reason.

Steps:

Load the location inventory.
Open Report Tester/Damage/Loss.
Click Open Products List.
Select the product.
Enter Select Quantity.
Choose Select Reason:
Damaged
Lost
Tester
Other
Add Comments.
Click Report Loss.

Visible fields:

Select Product
Select Quantity
Select Reason
Comments
Max
No product selected

Log columns:

Timestamp
Barcode
Product Name
Quantity
Reason
Reported By
Receive Inventory Transfer

Use Receive Inventory Transfer when inventory was sent from another location.

Steps:

Load the destination location inventory.
Open Receive Inventory Transfer.
Find the transfer.
Click Receive Transfer.
Review the transfer items.
Enter Quantity Received, or check receive the exact quantity sent when correct.
Click Receive.

Transfer list columns:

ID
Sent From
Sent At
Sent By
Comment
Status
Receive Transfer

Receive dialog columns:

Category
Barcode
SKU
Product Name
Product Cost Price
Desc.
Size
Color
Quantity Sent
Quantity Received

Receive dialog options:

Check this box to display the quantity sent
Check this box to receive the exact quantity sent
Receive
Cancel
Inventory > Daily Counts

Use Daily Counts to review submitted inventory counts.

Steps:

Go to Inventory > Daily Counts.
Select From Date and To Date.
Load the list.
Click Open on a count.
Review differences.
Use Fix or Fix All only when the counted quantities should update inventory.
Click Mark as "Reviewed" when complete.
Click Save.

Count list columns:

Count #
Timestamp
Location Name
Status
Submitted By
Open
Comment
TypeID

Count detail actions:

Mark as "Reviewed"
Fix All
Save
Cancel

Count detail columns:

Barcode
Wholesaler
Category
Product Name
Desc.
Size
Color
Quantity
Count
Fix
Inventory > History

Use History to review saved inventory snapshots.

Steps:

Go to Inventory > History.
Open Settings if snapshot settings need to be changed.
Check Save Inventory History if snapshots should be saved.
Choose Daily or Weekly.
Select the weekday if weekly.
Save settings.
Open a snapshot from the history list.

History columns:

ID
Timestamp
Location
Number of Products
Action

Settings:

Save Inventory History
Frequency
Daily
Weekly
Limit of 100 snapshots per location
Inventory > View Changes / Updates Log

Use the inventory change log to review inventory movements.

Options:

Show Transfers
Show Products Removed
Show Products Added

Columns:

Timestamp
Source ->
-> Destination
Barcode
Product Name
Desc.
Size
Color
Quantity
Cost
Performed By
Comment
Automatic Purchase Orders

Use Automatic Purchase Orders to create a purchase order based on capacity/minimum quantities.

Steps:

Go to Inventory > Automatic Purchase Orders.
Select the locations to include.
Select the wholesaler.
Review Quantity To Order.
Review Estimated Cost Price.
Check Save the estimated cost as an expense if needed.
Check Send me a copy if needed.
Click Submit Purchase Order.

Wizard labels:

Select the locations to include in this report
Select the wholesaler you would like to submit this purchase order to
Review Quantity To Order
Submit Purchase Order
Estimated Cost Price
Save the estimated cost as an expense
Send me a copy
Common Customer Questions
Why are products still not showing after I added inventory?
Confirm the product is active in Products > Settings.
Confirm the product is assigned to the location.
Confirm quantity exists at that location in Inventory > Management.
Confirm the location does not block out-of-stock sales unless quantity is above zero.
How do I hide quantity during inventory count?
Go to Locations > Settings.
Click Edit Location.
Open Location Preferences.
Under Inventory, check Hide quantity in the inventory count screen.
Click Save.
Public KB Guide Sources
NovaFAQ: Inventory Count - By Item - https://www.novafaq.com/2016/01/12/inventory-count-by-item/
NovaFAQ: Receiving Inventory Transfers - https://www.novafaq.com/2013/04/15/receiving-inventory-transfers/
NovaFAQ: Updating The Inventory - https://www.novafaq.com/2013/04/15/copying-products-to-locations/
NovaFAQ: Colors of the Transfer Screen - https://www.novafaq.com/2013/04/15/colors-of-the-transfer-screen/
NovaKB: how do i copy product from one location to another - https://novakb.com/233
