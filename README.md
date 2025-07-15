# YOUR PROJECT TITLE
#### Video Demo:  <URL HERE>
#### Description:
Welcome to my CS50 final proyect, in this oportunity i implemented an iventory management page, that tracks inventory and currencies movements.
To do so the database uses mainly four tables: inventory, currencies, inventory_movements and currencies movement. Each table has its own html template where you can search, filter, sort and toggle the data, giving countless options to see information as needed.

#### Iventory:
In the inventory template we get to see all the products available and its information as code, name, category, stock, and price. This is the core of the project and the launch point for everything else to happen.
In this template we also have to possibility of add, edit and delete products, by this buttons we are able to modify our inventory database.

When adding a product all fields have to be filled except for quantity wich is automatically set to 0.

Every product has the its right edit and delete buttons, in edit you get to change all the fields except for id and quantity, as id is the main way to identify products, and quantity only can be modifyed by recording a movement.

Deleting a product only will be possible if its quantity is 0.

#### Currencies:
Similar to inventory, in our currency table are listed all the currencies available to use, also with the posibility to add and delete them.

When adding a currency its balance is automatically set too 0 and is given an id number.

Same as inventory, if you desire to delete a currency you have to make sure first that its blance is 0.

#### Register:
This Where are going to record all the movements related to the database, in order to do so, inventory and currencies have their own movements's tables where they are recorded.

When we get to register notice that they are three options  to choose: Movements, currencies in/outs, inventory in/outs. This is only to identify wich tables are related to the transaction, if it's set to movements it means that the transaction required to record a movement on both tables (for example: sales, return, pucharses, etc. These are operations that require to record movements in our inventory and our currencies and update thier values), the other two options are for when movements only imply one movement_table.

Once we select the nature of our movement we have to fill the form, depending of wich one you choose its only going to require the inputs that are related to it or all if both inventory and currency are include in the movement.




