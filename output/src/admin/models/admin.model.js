const { DataTypes } = require('sequelize');
const { sequelize } = require('../../common/config/database');

const Admin = sequelize.define('Admin', {

    id: { type: DataTypes.STRING, primaryKey: true, },

    username: { type: DataTypes.STRING,  },
}, {
  tableName: 'admins',
  timestamps: true,
  underscored: true,
});

module.exports = Admin;
