# Accounting Expenses AI FAQ V 2

Source: Zoom Knowledge Library browser export
KB ID: n669kbqjs5h1h01ev55em8ki
Article ID: cmp4k8ghl02xir207dlgkcl4u
Product lane: Nova Wave
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/n669kbqjs5h1h01ev55em8ki/articles/cmp4k8ghl02xir207dlgkcl4u
Updated: 05/13/2026, 05:17 PM

Extract table (Keep table structure)
question	answer
What is Accounting > Expenses used for in Nova Back Office?	Accounting > Expenses stores regional company/business expenses in Nova.
Where is the Accounting Expenses page in Nova Back Office?	Go to Back Office > Accounting > Expenses. The direct URL is https://backoffice.novapointofsale.com/expenses.
Who can access Accounting > Expenses in Nova Back Office?	Accounting > Expenses can be accessed by users with the Owner role, users with the Secretary role, or users with a custom role that includes the exact privilege key expenses, subject to their Region access.
What is the exact custom-role privilege key for Accounting > Expenses?	The exact custom-role privilege key is expenses.
Are expenses in Accounting > Expenses regional or account-wide?	Expenses are regional business expenses. Do not describe them as account-wide.
Can I assign an expense to a specific employee in Accounting > Expenses?	No. Accounting > Expenses does not assign expenses to a specific employee. If the business needs to repay an employee, use the User Report reimbursement workflow.
Can I assign an expense directly to a specific location in Accounting > Expenses?	No. Expenses have no location effect from the Expenses feature.
Do expenses entered in Accounting > Expenses affect Profit Loss Report?	Yes. Expenses are one documented cost input used by Profit Loss Report. For full Profit Loss Report logic, use Back Office > Accounting > Profit Loss Report.
Why might my Profit Loss Report look inaccurate in Nova?	One documented check is whether regional expenses were entered in Accounting > Expenses for the relevant date range. Profit Loss Report also has its own documented reporting logic in the General Reports knowledge source.
How do I create an expense category in Accounting > Expenses?	Go to Back Office > Accounting > Expenses, click EDIT CATEGORIES, enter the category in Add New Category*, and click ADD.
Where do I add predefined categories for Accounting > Expenses?	Go to Back Office > Accounting > Expenses and click EDIT CATEGORIES. Categories created there are available in the Category dropdown when creating expenses.
What happens if I delete an expense category in Accounting > Expenses?	Deleting an expense category does not delete existing expense records. Existing expense lines remain saved.
Why is my expense category missing when I add a new expense?	The Category dropdown uses predefined categories. Create the category first through Back Office > Accounting > Expenses > EDIT CATEGORIES.
How do I add a new expense in Accounting > Expenses?	Click ADD NEW EXPENSE, enter Amount*, select Category, enter Date*, optionally enter Details, and click ADD.
How do I create a recurring expense in Accounting > Expenses?	Click ADD NEW EXPENSE, enter the amount and category, turn on Convert to Recurring Expense, choose Every m/w*, choose the recurrence day, set Start Date* and End Date*, optionally enter details, and click ADD.
What recurring expense frequency options are documented in Accounting > Expenses?	The documented Every m/w* options are Weekly and Monthly.
What does Monthly mean for a recurring expense in Accounting > Expenses?	Monthly means the expense recurs on a selected day of the month.
What does Weekly mean for a recurring expense in Accounting > Expenses?	Weekly means the expense recurs every week on a selected day of the week.
How do I create monthly rent as a recurring expense in Accounting > Expenses?	Create a Rent category first, click ADD NEW EXPENSE, enter the rent amount, choose Rent as the Category, turn on Convert to Recurring Expense, choose Monthly, choose the day of the month, set Start Date* and End Date*, add details if needed, and click ADD.
Why do I not see the recurring expense I just created in Accounting > Expenses?	Check the From and To date range. Expenses only appear when their expense date is included in the selected date range.
Why did my May 1 rent expense not appear when the Expenses page was filtered from May 6 to May 13?	The rent expense date was outside the selected range. Expand From and To so the range includes May 1.
How do I see recurring expenses through the end of the year in Accounting > Expenses?	Expand the To date so the selected date range includes the recurring entries you want to review, such as through the end of December.
How far into the future should I create recurring expenses?	Use shorter recurring periods, such as a few months or about one year at most. Recurring expenses create actual lines, and each generated line must be deleted individually if cleanup is needed later.
Why should I avoid creating recurring expenses too far into the future?	Recurring expenses create actual lines. For example, monthly rent through 2036 creates about 120 lines, and each line must be found and deleted individually if cleanup is needed later.
What does the Total Expenses card mean in Accounting > Expenses?	The page labels it Total Expenses and states Total Expenses according to the given dates. It summarizes expenses in the selected date range.
What summary appears when expenses exist in Accounting > Expenses?	The page shows a category-total table, a donut chart, and a red Total Expenses summary card for the selected date range.
What columns are shown in the Region Expenses table?	The documented columns are Id, Category Name & Time, Employee Name, Details, Total Cost, and Actions.
What does the OPTIONS menu show for an expense row?	The OPTIONS menu shows Edit and Delete.
How do I edit one expense in Accounting > Expenses?	Find the row in Region Expenses, click OPTIONS, and choose Edit. The Edit Expense drawer opens with Amount*, Category, Date*, Details, SAVE, and CANCEL.
Does editing one recurring expense row change the full recurring expense series?	No. Editing a recurring expense row edits only that specific entry. It does not change the full recurring series or future generated entries.
If one month's rent is different, how do I change only that month in Accounting > Expenses?	Open Region Expenses, click OPTIONS on that rent row, choose Edit, change that one expense, and save. Future recurrence entries keep the original recurring setup values.
What does Delete do from an expense row in Accounting > Expenses?	Delete removes only the selected visible expense line.
Does deleting one recurring expense row delete future recurring expenses?	No. Deleting one row deletes only that selected visible line. Future generated entries are not removed.
How do I remove generated recurring expense entries in Accounting > Expenses?	Find each generated expense line and delete the lines one by one. The walkthrough did not document a full-series delete action.
Can I download expenses from Accounting > Expenses?	Yes. Click Download in Excel in the Region Expenses section. It downloads a CSV containing the expenses currently in view.
Does Download in Excel export every expense in the system?	No. Download in Excel exports only the expenses currently in view based on the selected filters/date range.
What should I check first if an expense is missing from Accounting > Expenses?	Check the From and To date range first. The expense must fall within the selected date range to appear.
What should I do if Accounting > Expenses is missing for a user?	Confirm the user is in Back Office, has the correct Region access, and has Owner, Secretary, or a custom role with the expenses privilege.
How do I reimburse an employee for something they paid for?	Do not use Accounting > Expenses for employee-specific repayment. Use the reimbursement workflow in Back Office > Users > Report.
Should employee lunch reimbursement be entered in Accounting > Expenses?	No. If the business needs to repay an employee for lunch or another employee-paid item, use the employee reimbursement workflow in Back Office > Users > Report.
