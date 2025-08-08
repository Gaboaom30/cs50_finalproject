# Ludari

## Video Demo
[Watch the demo](<https://youtu.be/YIH6dS_uQ0c>)

## Description

Welcome to my **CS50 final project**!  
For this opportunity, I created an **inventory management web app** that tracks both inventory and currency movements.

The database uses four main tables:
- `inventory`
- `currencies`
- `inventory_movements`
- `currencies_movements`

Each table has its own HTML template where you can **search**, **filter**, **sort**, and **toggle** the data—giving you countless ways to see the information you need.

---

## Inventory

The **inventory** template lets you see all products and their details: code, name, category, stock, and price.  
This is the core of the project and the launch point for everything else.

**Features:**
- **Add, edit, or delete products**
  - When adding a product, all fields must be filled out except for quantity (which is set to `0` by default).
  - Each product has **Edit** and **Delete** buttons.
  - In **Edit**, you can change all fields except `id` (the unique identifier) and `quantity` (which can only be modified by recording a movement).
  - **Deleting** a product is only possible if its quantity is `0`.

---

## Currencies

The **currencies** table is similar to inventory. Here, you can view, add, and delete all available currencies.

**Features:**
- When adding a currency, its balance is automatically set to `0` and it’s assigned an ID.
- You can only delete a currency if its balance is `0`.

---

## Register

This is where you record all movements in the database.  
Inventory and currencies each have their own movement tables.

When you go to **Register**, you can choose from:
1. **Movements** (affecting both inventory and currencies, e.g., sales, returns, purchases)
2. **Currencies in/out**
3. **Inventory in/out**

**How it works:**
- Your choice determines which tables are involved in the transaction.
- If you select **Movements**, it means the transaction involves both tables. The other options are for transactions involving only one table.

**Process:**
1. Fill out the form (the required fields change depending on your selection). Select type(if inventory: sale, pucharse, return, output, input. If currency: income, expense), Code, name, quantity, price, note and status.
2. Click **Add** to save the movement as a draft.
3. Repeat as needed for additional movements.
4. When you’re done, click **Confirm**, and the program will check all the information and then save it:
   - All draft movements are saved to the database.
   - Inventory stock and currency balances are updated.
   - Each movement is assigned a shared `document_id` and `draft_id` to group related movements (e.g., an inventory movement and a currency movement for the same sale). Thanks to it was possible to implement a multipayment method option that lets you attach differents payments to a inventory movement. This was one os the hardest parts to figure out as i specifycally wanted to have multipayment methods.

---

## Inventory Movements

This page shows a list of all inventory movements that have been recorded.

---

## Currency Movements

This section shows all currency movements. It’s integrated into the currencies template.

---

## Index

The **Index** page includes two tables by default (but you can add more if you want):

- **Credit Sales Table:**  
  When you register a sale with payment set to "credit," it appears here. You can update payments directly from this table. Each payment adds two currency movements with the same `draft_id` and `document_id`:  
    - One for the payment received  
    - One for the negative credit movement  
  This lets you track how much of each sale has been paid until the debt is settled.

- **Delivery Table:**  
  This table shows all movements where the status is "to deliver," so you can track pending deliveries for customers.

---

## Responsive layout
The page is fully responsive, allowing you to work in any screen size