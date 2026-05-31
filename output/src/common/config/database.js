// Database: PostgreSQL
const { Sequelize } = require('sequelize');
const sequelize = new Sequelize(process.env.DATABASE_URL || 'postgresql://localhost:5432/space-fractions', { logging: false });
module.exports = { sequelize };
