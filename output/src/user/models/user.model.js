const { DataTypes } = require('sequelize');
const { sequelize } = require('../../common/config/database');

const User = sequelize.define('User', {

    id: { type: DataTypes.STRING, primaryKey: true, },

    username: { type: DataTypes.STRING,  },
}, {
  tableName: 'space-fractions_users',
  timestamps: true,
  underscored: true,
});

module.exports = User;
