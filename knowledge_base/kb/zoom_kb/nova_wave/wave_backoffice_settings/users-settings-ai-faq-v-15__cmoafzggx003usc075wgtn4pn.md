# Users Settings AI FAQ V 15

Source: Zoom Knowledge Library browser export
KB ID: n669kbqjs5h1h01ev55em8ki
Article ID: cmoafzggx003usc075wgtn4pn
Product lane: Nova Wave
Source URL: https://novapointofsale.zoom.us/ai-studio/kb/kbs/n669kbqjs5h1h01ev55em8ki/articles/cmoafzggx003usc075wgtn4pn
Updated: 05/18/2026, 05:22 PM

Q: Who can access Users -> Settings?

A: Owner, Partial Owner, and Regional Manager can access Back Office -> Users -> Settings.

Q: What is the difference between a user and an employee in Nova?

A: In this knowledge base, user, employee, and person in the system should be treated as the same core object: the user record.

Q: Is the title under the username the user's real access level?

A: No. The title shown under the username is an optional free-text title or job-title field. It is not the real permission model.

Q: How do I create a new employee?

A: Go to Back Office -> Users -> Settings and click Add New User. Enter User Name* because it is the only required field. Then review USER ACCESS LEVEL, assign the needed Regions, review the default Sales Representative role, decide whether additional roles or custom roles are needed, and review USER SALARY if Nova salary setup is required. Save with SUBMIT, SUBMIT & NEW, or SUBMIT & CLONE.

Q: How do I create a new user?

A: Go to Back Office -> Users -> Settings and click Add New User. Enter User Name* because it is the only required field. Then review USER ACCESS LEVEL, assign the needed Regions, review the default Sales Representative role, decide whether additional roles or custom roles are needed, and review USER SALARY if Nova salary setup is required. Save with SUBMIT, SUBMIT & NEW, or SUBMIT & CLONE.

Q: What is required to create a user?

A: Only User Name* is required.

Q: Does a user need a password?

A: No. Password is optional.

Q: Can a user sign in with no password?

A: Yes. A user can exist with no password.

Q: Can I reuse a username from an inactive user?

A: No. Username must remain unique even if the existing user is inactive.

Q: Are usernames case sensitive?

A: No. Usernames are not case sensitive.

Q: Can usernames include spaces?

A: Yes. Usernames can include spaces.

Q: Can usernames include special characters?

A: Yes. Usernames can include spaces, numbers, and special characters.

Q: Can I delete a user?

A: No. Nova does not delete users from this workflow. It deactivates them.

Q: Can User ID 1 be deactivated?

A: No. User ID 1 is the special administrative user and cannot be deactivated.

Q: Can inactive users be edited?

A: Yes. Inactive users can still be opened and edited.

Q: Can inactive users be activated again?

A: Yes. Inactive users can still be activated again.

Q: What does Submit and Clone do when creating a user?

A: Submit and Clone saves the record and starts a copied-record workflow. It copies all fields except username, and it also copies salary and access-level settings.

Q: Are all user-information fields validated?

A: No special validation rules are documented for the available user-creation fields other than the username uniqueness rule.

Q: What is Carrier used for in user settings?

A: Carrier is the dropdown used for SMS-alert style behavior if the business uses that setup.

Q: Does Mobile# require Carrier?

A: No. Mobile# can be saved without Carrier as informational data.

Q: Should we use SMS alerts for employees?

A: The recommended direction is the mobile app rather than SMS alerts.

Q: What happens if a user record has no email?

A: If there is no email on the user record, the paycheck cannot be emailed and the forgot password function cannot be used.

Q: What happens if a user record has an email?

A: If the user record has an email assigned, Nova can email the paycheck when a paycheck is issued, and the user can also use the forgot password function and receive the password by email.

Q: Should privileged users use stronger passwords?

A: Yes. Privileged users such as Owner, Partial Owner, and Regional Manager should use stronger passwords, should not share those passwords, and should rotate them periodically.

Q: Do I have to use Nova salary?

A: No. USER SALARY is optional.

Q: Is salary in Nova daily or weekly?

A: Salary in Nova is a daily calculation only.

Q: Is commission in Nova daily or weekly?

A: Commission in Nova is a daily calculation only.

Q: Can Nova calculate weekly commission?

A: No. Nova commission is calculated daily.

Q: Can Nova calculate monthly commission?

A: No. Nova commission is calculated daily.

Q: Can Nova calculate a custom time-frame commission?

A: No. Nova commission is calculated daily.

Q: Can Nova automatically calculate bonuses?

A: No. Nova does not offer an automatic bonus feature. Reimbursements can be added manually and will print on payroll.

Q: How do I handle a payroll setup that Nova does not support?

A: Nova's native salary options are the primary supported setup in this guide. If the business needs a payroll model outside those native options, it can use API access or export data to a third-party workflow such as QuickBooks or an accountant-managed process.

Q: What happens when one user works in multiple locations?

A: Nova salary calculates the day's sales across all locations for that user.

Q: How do I separate salary by location for the same person?

A: Create two different user records.

Q: Why did my employee not receive product commission?

A: Check the Product Commission toggle in USER SALARY. If it is off, the user does not participate in product-level commission plans.

Q: Can hourly pay include break time?

A: Yes, if Include break in total hour count. is turned on.

Q: How are partial hours paid?

A: Partial hours are converted to decimal time and paid down to the minute.

Q: What is the difference between flat commission and commission steps?

A: Flat commission has no ceiling. Commission steps use daily brackets and can create different rates at different daily sales levels.

Q: What does Retro do in commission steps?

A: Retro applies the reached step percentage to the whole qualifying amount for the steps where Retro is checked. Each step has its own Retro checkbox, so the business can mix differential and Retro behavior across steps.

Q: What happens if a user has no roles at all?

A: The user can still sign into Storefront and make sales, but they do not get Back Office access from that setup.

Q: What does Sales Representative do?

A: Sales Representative gives refund access and chat access. A user can still make sales without that role.

Q: How do I give an employee access only to one screen?

A: Create a custom role with only the needed privilege selected, then assign that custom role to the employee.

Q: How do I give someone access only to Invoices?

A: Go to Back Office -> Users -> Settings -> Edit User -> USER ACCESS LEVEL -> Custom Roles -> CREATE ROLE, create a role with only invoices selected, then assign that custom role to the employee.

Q: What does a role do?

A: A role grants a defined set of privileges. The correct support answer is to list the privileges included in that role using friendly wording.

Q: What does Full Owner do?

A: Full Owner gives access to all Regions, all users, invoice deletion, invoice date changes, data protection, change logs, coupons, and billing automation.

Q: What does Partial Owner do?

A: Partial Owner gives access to the realtime dashboard with profit, creating users with Partial Owner access, location settings, invoices, payments, store credit, refunds, profit and loss reporting, and dynamic reports.

Q: What does Regional Manager do?

A: Regional Manager gives access to the realtime dashboard without profit, creating users with Regional Manager access, user settings, location reports, approving sales under minimum price, editing invoice commission, cash register activity, end of day reports, force checkout, open cash register, tax-exempt sales, and live camera access.

Q: What does the Full Owner role do in Nova?

A: Full Owner gives access to all Regions, all users, invoice deletion, invoice date changes, data protection, change logs, coupons, and billing automation.

Q: What can a Full Owner do in Nova?

A: Full Owner gives access to all Regions, all users, invoice deletion, invoice date changes, data protection, change logs, coupons, and billing automation.

Q: What access does a Full Owner have in Nova?

A: Full Owner gives access to all Regions, all users, invoice deletion, invoice date changes, data protection, change logs, coupons, and billing automation.

Q: What permissions does a Full Owner have in Nova?

A: Full Owner gives access to all Regions, all users, invoice deletion, invoice date changes, data protection, change logs, coupons, and billing automation.

Q: What does the Partial Owner role do in Nova?

A: Partial Owner gives access to the realtime dashboard with profit, creating users with Partial Owner access, location settings, invoices, payments, store credit, refunds, profit and loss reporting, and dynamic reports.

Q: What can a Partial Owner do in Nova?

A: Partial Owner gives access to the realtime dashboard with profit, creating users with Partial Owner access, location settings, invoices, payments, store credit, refunds, profit and loss reporting, and dynamic reports.

Q: What access does a Partial Owner have in Nova?

A: Partial Owner gives access to the realtime dashboard with profit, creating users with Partial Owner access, location settings, invoices, payments, store credit, refunds, profit and loss reporting, and dynamic reports.

Q: What permissions does a Partial Owner have in Nova?

A: Partial Owner gives access to the realtime dashboard with profit, creating users with Partial Owner access, location settings, invoices, payments, store credit, refunds, profit and loss reporting, and dynamic reports.

Q: What does the Regional Manager role do in Nova?

A: Regional Manager gives access to the realtime dashboard without profit, creating users with Regional Manager access, user settings, location reports, approving sales under minimum price, editing invoice commission, cash register activity, end of day reports, force checkout, open cash register, tax-exempt sales, and live camera access.

Q: What can a Regional Manager do in Nova?

A: Regional Manager gives access to the realtime dashboard without profit, creating users with Regional Manager access, user settings, location reports, approving sales under minimum price, editing invoice commission, cash register activity, end of day reports, force checkout, open cash register, tax-exempt sales, and live camera access.

Q: What access does a Regional Manager have in Nova?

A: Regional Manager gives access to the realtime dashboard without profit, creating users with Regional Manager access, user settings, location reports, approving sales under minimum price, editing invoice commission, cash register activity, end of day reports, force checkout, open cash register, tax-exempt sales, and live camera access.

Q: What permissions does a Regional Manager have in Nova?

A: Regional Manager gives access to the realtime dashboard without profit, creating users with Regional Manager access, user settings, location reports, approving sales under minimum price, editing invoice commission, cash register activity, end of day reports, force checkout, open cash register, tax-exempt sales, and live camera access.

Q: How do I give partner access?

A: Start with Partial Owner, review the privileges included in Partial Owner, then define what the person actually needs to do in the system. Based on that requirement, use Partial Owner alone, Partial Owner plus other system roles, or narrower custom-role access if broad access is not wanted.

Q: Can one user have different roles in different Regions?

A: No. If a user has access to more than one Region, the same granted roles and privileges apply in all of those Regions.

Q: What is the workaround if I want one person to have different access in different Regions?

A: Create two separate user records. For example, one user for Region 1 and another user for Region 2. Important: salary will also be separated because Nova treats them as two different employees.

Q: Can Regional Manager edit user access?

A: No. Regional Manager cannot edit user access.

Q: Can Regional Manager create custom roles?

A: No.

Q: Can Partial Owner create custom roles?

A: No.

Q: Can Partial Owner give themselves Full Owner?

A: No.

Q: Does Salary Report access let me edit salary settings?

A: No. Salary Report access only allows viewing the report. It does not grant user-settings edit access.

Q: What happens if I delete a custom role?

A: It is removed from all employees that had that role assigned.

Q: Should I be careful with the type of accesses I give?

A: Yes. Broad roles should be granted carefully. If the business wants one screen or one narrow capability only, use a custom role instead of a broad role.

Q: How do I create a manager?

A: Create the user in Back Office -> Users -> Settings -> Add New User, then review USER ACCESS LEVEL. Choose the manager setup based on what the person needs to do. Regional Manager is the starting point for manager-style access, but additional lateral roles or custom roles may still be needed. Only Owner can assign those roles.

Q: How do I create a partner?

A: Create the user, then start with Partial Owner in USER ACCESS LEVEL. After that, clarify what actions the person needs to perform, because Partial Owner may still need additional roles or custom-role access depending on the tasks.

Q: How do I create a partner without giving them full access?

A: Use Partial Owner as the starting point instead of Full Owner, then review what actions the person actually needs. Add only the lower roles they need, or use custom roles for narrower access. Only Owner can assign or change those roles.

Q: How do I create a user step by step in Nova?

A: Go to Back Office -> Users -> Settings -> Add New User. In USER INFORMATION, enter User Name*. Optionally enter password, title, contact details, notes, and address details. Confirm whether the user should remain Active. Then open USER ACCESS LEVEL, assign the needed Regions, review the default Sales Representative role, and add other roles or custom roles if needed. If the business wants Nova salary logic for this user, open USER SALARY and configure it. Then save with SUBMIT, SUBMIT & NEW, or SUBMIT & CLONE.

Q: What access should I give to a new employee in Nova?

A: Give the role that matches what they will actually do, then tighten access if needed. Product Manager is the starting point for product work, Inventory Manager for inventory work, Secretary for reporting and payroll-helper work, Partial Owner for partner-style access, and Regional Manager for manager-style access. If they need only one screen or one narrow function, use a custom role instead of a broad role. Also review Region access and USER SALARY if those matter for the setup.

Q: How should I set up salary for a user in Nova?

A: Use USER SALARY on the user's record and set up the pay model directly in Nova. For most customers, the usual commission setup is either Flat Commission or Commission Steps. Use Flat Commission if you want one commission percentage on all sales. Use Commission Steps if you want a tiered commission model based on sales performance. Hourly is also common for some businesses. Product Commission is a more specialized setup and should not be the default starting point unless you specifically need product-based commission. Nova salary and commission are daily calculations only.

Q: What are all the salary options in USER SALARY?

A: In USER SALARY, Nova supports Flat Commission, Hourly, Include break in total hour count, Base Salary, Added to Salary, Added on, Expense to Location, Product Commission, Higher of Commission or Hourly, Commission Steps, Retro, and Copy Salary from User. For most customers, the most common commission setup is either Flat Commission or Commission Steps. Flat Commission pays a daily commission on the user's net sales. Commission Steps create a differential compensation model based on employee performance using daily sales brackets. Hourly pays exact worked time down to the minute. Base Salary is a flat amount scheduled weekly or monthly. Product Commission includes the user in product-level commission plans, but it is a more specialized setup and not the most common starting point. Higher of Commission or Hourly compares the day's commission result to the day's hourly result and pays the higher one. Retro applies the reached step percentage to the whole qualifying amount for the steps where Retro is checked.

Q: What does Base Salary mean in USER SALARY?

A: Base Salary is a flat amount scheduled weekly or monthly. It is not a daily amount.

Q: What are Commission Steps in USER SALARY?

A: Commission Steps are a differential compensation model based on employee performance using daily sales brackets. Different daily sales levels can pay different commission percentages.

Q: Why can't I edit the From field in Commission Steps?

A: The From field in later Commission Steps is system-controlled. Nova starts each step wherever the previous active step's To field ends. To change Step 2's starting amount, change Step 1's To amount. To change Step 3's starting amount, change Step 2's To amount.

Q: Why is the commission From amount greyed out?

A: Nova greys out later step From values because they are calculated from the previous active step's To value. This keeps commission brackets continuous and prevents gaps or overlapping commission ranges.

Q: How do I change where Step 2 starts in commission settings?

A: Go to Back Office -> Users -> Settings, open the user, open USER SALARY, then go to Salary & Commission -> Commission Steps. Change Step 1's To(s) / To($) value. Nova uses that value as Step 2's From(s) / From($) value.

Q: Can I manually type a From amount into a commission step?

A: No. In Commission Steps, later From values are not manually entered. Edit the previous step's To value and Nova will use that amount as the next step's From value.

Q: Why do I get access denied in Users Settings?

A: That access denied message usually means your user does not have permission to access Back Office -> Users -> Settings. Only Owner, Partial Owner, and Regional Manager can access that screen.

Q: Why do I not see this employee on the salary report?

A: Payroll questions are sensitive and business-critical. Go to Back Office -> Users -> Settings, open the employee, and open the USER SALARY tab to verify the basic pay setup. If possible, identify the exact affected day. For deeper review, connect with a support agent.

Q: Why is the employee receiving the wrong salary amount?

A: Payroll questions are sensitive and business-critical. Go to Back Office -> Users -> Settings, open the employee, and open the USER SALARY tab to verify the basic pay setup. If possible, identify the exact affected day. For deeper review, connect with a support agent.

Q: Why is the employee salary too high?

A: Payroll questions are sensitive and business-critical. Go to Back Office -> Users -> Settings, open the employee, and open the USER SALARY tab to verify the basic pay setup. If possible, identify the exact affected day. For deeper review, connect with a support agent.

Q: Why is the employee salary too low?

A: Payroll questions are sensitive and business-critical. Go to Back Office -> Users -> Settings, open the employee, and open the USER SALARY tab to verify the basic pay setup. If possible, identify the exact affected day. For deeper review, connect with a support agent.

Q: Why is the salary amount inaccurate?

A: Payroll questions are sensitive and business-critical. Go to Back Office -> Users -> Settings, open the employee, and open the USER SALARY tab to verify the basic pay setup. If possible, identify the exact affected day. For deeper review, connect with a support agent.

Q: What should I check first if salary looks wrong in Nova?

A: Payroll questions are sensitive and business-critical. Go to Back Office -> Users -> Settings, open the employee, and open the USER SALARY tab to verify the basic pay setup. If possible, identify the exact affected day. For deeper review, connect with a support agent.

Q: What should I do if I think there is a discrepancy in one employee's pay?

A: Payroll questions are sensitive and business-critical. Go to Back Office -> Users -> Settings, open the employee, and open the USER SALARY tab to verify the basic pay setup. If possible, identify the exact affected day. For deeper review, connect with a support agent.

Q: What should I do if I think one invoice gave too much commission to an employee?

A: Payroll questions are sensitive and business-critical. Remember that Nova calculates commission daily. Then go to Back Office -> Users -> Settings, open the employee, and open the USER SALARY tab to verify the basic pay setup. If possible, identify the exact affected day. For deeper review, connect with a support agent.

Q: I enabled product commission, but the user is not getting it. What should I check?

A: First, go to Back Office -> Users -> Settings, open the user, and go to USER SALARY. Verify that Product Commission is turned on for that user. Then verify the product has the correct Commission Policy. Remember that all commission in Nova is based on the pre-tax, post-discount net value of the sale.

Q: Why is product commission not showing for the employee?

A: Go to Back Office -> Users -> Settings, open the user, and go to USER SALARY. Verify that Product Commission is turned on for that user. Then verify the product has the correct Commission Policy. Remember that all commission in Nova is based on the pre-tax, post-discount net value of the sale.

Q: Is commission calculated before or after tax in Nova?

A: Commission in Nova is calculated before tax. There is no commission on tax.

Q: Is commission calculated before or after discount in Nova?

A: Commission in Nova is calculated after discount. It is based on the final discounted amount.

Q: Can I give commission on the wholesale amount in Nova?

A: No. Commission in Nova is always based on the pre-tax, post-discount net value of the sale.

Q: Can Nova give performance bonuses automatically?

A: No. Nova does not offer an automatic bonus feature based on employee performance. Reimbursements can be added manually and will print on payroll.

Q: Can Nova give location-based bonuses automatically?

A: No. Nova does not offer an automatic bonus feature based on location performance. Reimbursements can be added manually and will print on payroll.

Q: How do I add a bonus manually in Nova?

A: Nova does not offer an automatic bonus feature, but reimbursements can be added manually and will print on payroll.

Q: What is the most common way to set up commission for an employee in Nova?

A: For most customers, the most common commission setup is either Flat Commission or Commission Steps in the USER SALARY tab.

Q: Should I use Flat Commission or Product Commission for most employees in Nova?

A: For most employees, start with Flat Commission or Commission Steps. Product Commission is a more specialized setup and should not be the default starting point unless you specifically need product-based commission.

Q: What is the most common salary setup for a salesperson in Nova?

A: For most salespeople, the most common setup is Flat Commission or Commission Steps in the USER SALARY tab.

Q: How should I usually set up a manager who also earns commission in Nova?

A: If a manager also earns commission, go to USER SALARY on that user's record. For most customers, the usual setup is Flat Commission or Commission Steps. Product Commission is a more specialized option and should not be the default starting point unless you specifically need product-based commission.

Q: What should I do if I am still not sure what is wrong with the paycheck after checking USER SALARY?

A: Payroll questions are sensitive and business-critical. After checking the USER SALARY tab and identifying the affected day if possible, connect with a support agent for deeper review.
