# Task
Read the receipt in the file you are given, and return it as one CSV line.

# Steps
Run by code, in this order, for every file in inbox/:
1. The code gives you one file.
2. You read its date, vendor, total amount, and currency.
3. You return one line: date (YYYY-MM-DD),vendor,amount,currency. Nothing else.
4. The code appends your line to expenses.csv.

# Why
The rows feed my reimbursement claim. A guessed field is worse than an empty one.

# Done
Every field matches the receipt. A field you cannot read is written as UNREADABLE, never guessed.

# Boundaries
❌ Never return anything but the one line.

# Sources
The file you are given.
