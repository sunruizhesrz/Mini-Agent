const { DataTypes } = require('sequelize');
const { sequelize } = require('../../common/config/database');

const Game = sequelize.define('Game', {

    id: { type: DataTypes.INTEGER, primaryKey: true, autoIncrement: true, },

    game_state: { type: DataTypes.JSONB,  },
}, {
  tableName: 'games',
  timestamps: true,
  underscored: true,
});

module.exports = Game;
