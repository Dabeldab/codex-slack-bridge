<!-- AgentChat/direct_codex 2026-07-27T21:24:14Z -->
# Nova Database Enum Reference

Source: Google Drive document `Copy of Nova Enums`, owned by Darius Parlor.

Accessible Drive source ID: `1oZZz7zsnHG-vMThiPcnlxeGZs3ldqi97rRWA-7XRMNA`

Operator-supplied source ID: `1XFttHAzN7EGD7AkytpnLO_A5oqwUT5GvhcCcTlX0ipY`

Source version: 34

Source modified: 2021-01-13T19:50:58.783Z

Scope: Nova Classic database and application enum mappings. These values are reference data, not authorization to mutate a database. Verify the live schema and exact business context before using them in SQL.

## CommissionTypeEnum

| Name | Value |
| --- | ---: |
| NoCommission | 1 |
| RegularCommission | 2 |
| ExtraCommission | 3 |

## ChangeLogType

| Name | Value |
| --- | ---: |
| Unknown | 0 |
| InvoiceDeleted | 1 |
| InvoiceChanged | 2 |
| InvoiceEmployeeCommissionChanged | 3 |
| LayawayDeleted | 4 |
| HoursChanged | 5 |
| InvoiceEmployeeTipChanged | 6 |
| Damaged | 7 |
| InvoiceEmployeeNonCommissionChanged | 8 |

## Log_TypeID

| Name | Value |
| --- | ---: |
| Invoice_Deleted | 1 |
| Invoice_Changed | 2 |
| Invoice_Employee_Commission_Changed | 3 |
| Layaway_Deleted | 4 |
| Hours_Changed | 5 |
| Invoice_Employee_Tip_Changed | 6 |
| Damaged | 7 |
| Invoice_Employee_Non_Commission_Changed | 8 |

## Invoice_TypeID

| Name | Value |
| --- | ---: |
| Invoice | 1 |
| Invoice_TaxExempt | 2 |
| Invoice_Refund | 3 |
| Invoice_Layaway | 4 |
| Invoice_Exchange | 5 |

The source text omitted a comma after `Invoice_Layaway = 4`; the name-to-value mapping itself is unambiguous.

## CustomerOrder_TypeID

| Name | Value |
| --- | ---: |
| Layaway | 1 |

## CustomerOrderStatus_ID

| Name | Value |
| --- | ---: |
| Active | 1 |
| Canceled | 2 |

## Alerts

| Name | Value |
| --- | ---: |
| FirstLastCheckIn | 1 |
| FirstSale | 2 |
| LargeSale | 3 |
| LargeSaleByEmployee | 4 |
| MinPriceCodeApproval | 5 |
| MinPriceApproved | 6 |
| SMSAsChat | 7 |
| EmployeeLongBreak | 8 |
| EndOfDayReport | 9 |
| RefundPerformed | 10 |
| CRMCollection | 11 |
| TesterLoss | 12 |
| CommissionChange | 13 |
| MinCapacity | 14 |
| CountError | 15 |
| CashCount | 16 |
| FirstEmployeeCheckIn | 17 |
| LocationSalesHigher | 18 |
| ExchangeMadeByRepresentative | 19 |
| NoSalesMade | 20 |
| TransferRequest | 21 |
| CompletedLayaway | 22 |
| AutomaticCheckOut | 23 |
| EveryCheckInAndOut | 24 |
| EmployeeHoursChanged | 25 |
| InventoryCountNotCreatedOnSchedule | 26 |
| StellarManualRefundAmount | 27 |

## Source guidance

The original document notes that additional enum declarations can be located in the Nova source code by searching for `public enum`.
