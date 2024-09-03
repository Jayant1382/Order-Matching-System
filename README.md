1. Database Design
Tables Overview
Pending Orders Table: Stores all the current buy and sell orders that are yet to be matched.
Completed Orders Table: Stores all orders that have been successfully matched.

Pending Orders Table
sql
CREATE TABLE pending_orders (
    id SERIAL PRIMARY KEY,
    order_type VARCHAR(10) NOT NULL CHECK (order_type IN ('BUY', 'SELL')),
    quantity INT NOT NULL CHECK (quantity > 0),
    price DECIMAL(10, 2) NOT NULL CHECK (price > 0),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
Completed Orders Table
sql
CREATE TABLE completed_orders (
    id SERIAL PRIMARY KEY,
    price DECIMAL(10, 2) NOT NULL,
    quantity INT NOT NULL,
    buyer_order_id INT REFERENCES pending_orders(id),
    seller_order_id INT REFERENCES pending_orders(id),
    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
Indexes for Performance


CREATE INDEX idx_pending_orders_price ON pending_orders(price);
CREATE INDEX idx_pending_orders_type_price ON pending_orders(order_type, price);


2. Backend Implementation


Setup
Initialize the Project


mkdir order-matching-system
cd order-matching-system
npm init -y
npm install express sequelize pg pg-hstore body-parser
Sequelize Configuration

Configure Sequelize to connect to your PostgreSQL database.

javascript

const { Sequelize } = require('sequelize');

const sequelize = new Sequelize('database', 'username', 'password', {
    host: 'localhost',
    dialect: 'postgres',
    logging: false,
});

module.exports = sequelize;
Define Models


// models/PendingOrder.js
const { DataTypes } = require('sequelize');
const sequelize = require('../config/database');

const PendingOrder = sequelize.define('PendingOrder', {
    order_type: {
        type: DataTypes.ENUM('BUY', 'SELL'),
        allowNull: false,
    },
    quantity: {
        type: DataTypes.INTEGER,
        allowNull: false,
        validate: { min: 1 },
    },
    price: {
        type: DataTypes.DECIMAL(10, 2),
        allowNull: false,
        validate: { min: 0.01 },
    },
}, {
    tableName: 'pending_orders',
    timestamps: true,
    createdAt: 'created_at',
    updatedAt: false,
});

module.exports = PendingOrder;

// models/CompletedOrder.js
const { DataTypes } = require('sequelize');
const sequelize = require('../config/database');

const CompletedOrder = sequelize.define('CompletedOrder', {
    price: {
        type: DataTypes.DECIMAL(10, 2),
        allowNull: false,
    },
    quantity: {
        type: DataTypes.INTEGER,
        allowNull: false,
    },
    buyer_order_id: {
        type: DataTypes.INTEGER,
        references: {
            model: 'pending_orders',
            key: 'id',
        },
    },
    seller_order_id: {
        type: DataTypes.INTEGER,
        references: {
            model: 'pending_orders',
            key: 'id',
        },
    },
}, {
    tableName: 'completed_orders',
    timestamps: true,
    createdAt: 'completed_at',
    updatedAt: false,
});

module.exports = CompletedOrder;
Initialize Database


// models/index.js
const sequelize = require('../config/database');
const PendingOrder = require('./PendingOrder');
const CompletedOrder = require('./CompletedOrder');

const initDB = async () => {
    await sequelize.sync({ alter: true }); // Use { force: true } for development resets
    console.log('Database synchronized');
};

module.exports = {
    PendingOrder,
    CompletedOrder,
    initDB,
};
Order Matching Logic
Implement the core logic to match buy and sell orders.


// services/matchingService.js
const { PendingOrder, CompletedOrder, sequelize } = require('../models');
const { Op } = require('sequelize');

const matchOrders = async (newOrder) => {
    const transaction = await sequelize.transaction();
    try {
        if (newOrder.order_type === 'BUY') {
            // Find sell orders where seller price <= buyer price
            const sellOrders = await PendingOrder.findAll({
                where: {
                    order_type: 'SELL',
                    price: { [Op.lte]: newOrder.price },
                },
                order: [['price', 'ASC'], ['created_at', 'ASC']],
                transaction,
                lock: transaction.LOCK.UPDATE, // Lock the selected rows
            });

            for (let sellOrder of sellOrders) {
                if (newOrder.quantity === 0) break;

                const matchedQty = Math.min(newOrder.quantity, sellOrder.quantity);
                const matchedPrice = sellOrder.price; // Price can be seller's price

                // Create completed order
                await CompletedOrder.create({
                    price: matchedPrice,
                    quantity: matchedQty,
                    buyer_order_id: newOrder.id,
                    seller_order_id: sellOrder.id,
                }, { transaction });

                // Update quantities
                newOrder.quantity -= matchedQty;
                sellOrder.quantity -= matchedQty;

                if (sellOrder.quantity === 0) {
                    await sellOrder.destroy({ transaction });
                } else {
                    await sellOrder.save({ transaction });
                }
            }
        } else if (newOrder.order_type === 'SELL') {
            // Find buy orders where buyer price >= seller price
            const buyOrders = await PendingOrder.findAll({
                where: {
                    order_type: 'BUY',
                    price: { [Op.gte]: newOrder.price },
                },
                order: [['price', 'DESC'], ['created_at', 'ASC']],
                transaction,
                lock: transaction.LOCK.UPDATE,
            });

            for (let buyOrder of buyOrders) {
                if (newOrder.quantity === 0) break;

                const matchedQty = Math.min(newOrder.quantity, buyOrder.quantity);
                const matchedPrice = buyOrder.price; // Price can be buyer's price

                // Create completed order
                await CompletedOrder.create({
                    price: matchedPrice,
                    quantity: matchedQty,
                    buyer_order_id: buyOrder.id,
                    seller_order_id: newOrder.id,
                }, { transaction });

                // Update quantities
                newOrder.quantity -= matchedQty;
                buyOrder.quantity -= matchedQty;

                if (buyOrder.quantity === 0) {
                    await buyOrder.destroy({ transaction });
                } else {
                    await buyOrder.save({ transaction });
                }
            }
        }

        if (newOrder.quantity > 0) {
            // Remaining quantity stays in pending orders
            await newOrder.save({ transaction });
        } else {
            await newOrder.destroy({ transaction });
        }

        await transaction.commit();
    } catch (error) {
        await transaction.rollback();
        throw error;
    }
};

module.exports = { matchOrders };
API Endpoints
Implement RESTful API endpoints for managing orders.


// app.js
const express = require('express');
const bodyParser = require('body-parser');
const { initDB, PendingOrder, CompletedOrder } = require('./models');
const { matchOrders } = require('./services/matchingService');

const app = express();
app.use(bodyParser.json());

// Initialize Database
initDB();

// Get Pending Orders
app.get('/api/pending-orders', async (req, res) => {
    try {
        const orders = await PendingOrder.findAll();
        res.json(orders);
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

// Get Completed Orders
app.get('/api/completed-orders', async (req, res) => {
    try {
        const orders = await CompletedOrder.findAll();
        res.json(orders);
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

// Create New Order
app.post('/api/orders', async (req, res) => {
    const { order_type, quantity, price } = req.body;

    if (!['BUY', 'SELL'].includes(order_type)) {
        return res.status(400).json({ error: 'Invalid order type' });
    }

    if (quantity <= 0 || price <= 0) {
        return res.status(400).json({ error: 'Quantity and price must be positive' });
    }

    try {
        const newOrder = await PendingOrder.create({ order_type, quantity, price });

        // Perform matching
        await matchOrders(newOrder);

        res.status(201).json({ message: 'Order placed successfully' });
    } catch (error) {
        res.status(500).json({ error: error.message });
    }
});

// Start Server
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`Server is running on port ${PORT}`);
});


3. Frontend Development

npx create-react-app order-matching-frontend
cd order-matching-frontend
npm install axios react-bootstrap bootstrap
Configure Bootstrap


// src/index.js
import 'bootstrap/dist/css/bootstrap.min.css';
import React from 'react';
import ReactDOM from 'react-dom';
import App from './App';

ReactDOM.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
  document.getElementById('root')
);
Components
OrderForm Component
Allows users to place new buy or sell orders.


// src/components/OrderForm.js
import React, { useState } from 'react';
import { Form, Button, Spinner } from 'react-bootstrap';
import axios from 'axios';

const OrderForm = ({ onOrderPlaced }) => {
    const [orderType, setOrderType] = useState('BUY');
    const [quantity, setQuantity] = useState('');
    const [price, setPrice] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const handleSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        setError('');

        try {
            await axios.post('/api/orders', {
                order_type: orderType,
                quantity: parseInt(quantity),
                price: parseFloat(price),
            });
            onOrderPlaced();
            setQuantity('');
            setPrice('');
        } catch (err) {
            setError(err.response?.data?.error || 'An error occurred');
        } finally {
            setLoading(false);
        }
    };

    return (
        <Form onSubmit={handleSubmit}>
            <Form.Group controlId="orderType">
                <Form.Label>Order Type</Form.Label>
                <Form.Control as="select" value={orderType} onChange={(e) => setOrderType(e.target.value)}>
                    <option value="BUY">Buy</option>
                    <option value="SELL">Sell</option>
                </Form.Control>
            </Form.Group>

            <Form.Group controlId="quantity">
                <Form.Label>Quantity</Form.Label>
                <Form.Control
                    type="number"
                    value={quantity}
                    onChange={(e) => setQuantity(e.target.value)}
                    required
                    min="1"
                />
            </Form.Group>

            <Form.Group controlId="price">
                <Form.Label>Price</Form.Label>
                <Form.Control
                    type="number"
                    step="0.01"
                    value={price}
                    onChange={(e) => setPrice(e.target.value)}
                    required
                    min="0.01"
                />
            </Form.Group>

            {error && <p className="text-danger">{error}</p>}

            <Button variant="primary" type="submit" disabled={loading}>
                {loading ? <Spinner animation="border" size="sm" /> : 'Place Order'}
            </Button>
        </Form>
    );
};

export default OrderForm;
OrdersTable Component
Displays pending and completed orders.


// src/components/OrdersTable.js
import React from 'react';
import { Table } from 'react-bootstrap';

const OrdersTable = ({ title, orders, columns }) => (
    <div className="mt-4">
        <h3>{title}</h3>
        <Table striped bordered hover>
            <thead>
                <tr>
                    {columns.map((col, idx) => <th key={idx}>{col}</th>)}
                </tr>
            </thead>
            <tbody>
                {orders.map(order => (
                    <tr key={order.id}>
                        {columns.map((col, idx) => (
                            <td key={idx}>{order[col.toLowerCase().replace(' ', '_')]}</td>
                        ))}
                    </tr>
                ))}
            </tbody>
        </Table>
    </div>
);

export default OrdersTable;
App Component
Combines everything and manages state.


// src/App.js
import React, { useEffect, useState } from 'react';
import { Container, Row, Col } from 'react-bootstrap';
import OrderForm from './components/OrderForm';
import OrdersTable from './components/OrdersTable';
import axios from 'axios';

const App = () => {
    const [pendingOrders, setPendingOrders] = useState([]);
    const [completedOrders, setCompletedOrders] = useState([]);

    const fetchOrders = async () => {
        try {
            const [pendingRes, completedRes] = await Promise.all([
                axios.get('/api/pending-orders'),
                axios.get('/api/completed-orders'),
            ]);
            setPendingOrders(pendingRes.data);
            setCompletedOrders(completedRes.data);
        } catch (error) {
            console.error('Error fetching orders', error);
        }
    };

    useEffect(() => {
        fetchOrders();
    }, []);

    return (
        <Container>
            <Row className="mt-4">
                <Col>
                    <h1>Order Matching System</h1>
                </Col>
            </Row>
            <Row className="mt-4">
                <Col md={6}>
                    <OrderForm onOrderPlaced={fetchOrders} />
                </Col>
            </Row>
            <Row>
                <Col md={6}>
                    <OrdersTable
                        title="Pending Orders"
                        orders={pendingOrders}
                        columns={['Order Type', 'Quantity', 'Price', 'Created At']}
                    />
                </Col>
                <Col md={6}>
                    <OrdersTable
                        title="Completed Orders"
                        orders={completedOrders}
                        columns={['Price', 'Quantity', 'Completed At']}
                    />
                </Col>
            </Row>
        </Container>
    );
};

export default App;
Proxy Configuration
To route API calls from React to the backend server, add a proxy in package.json.


// package.json
{
  // ... existing content
  "proxy": "http://localhost:3000"
}



![Screenshot (721)](https://github.com/user-attachments/assets/a5b7169e-1187-4ec8-89b8-0dd140c8dea5)
