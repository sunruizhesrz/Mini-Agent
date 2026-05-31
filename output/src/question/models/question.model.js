const { DataTypes } = require('sequelize');
const { sequelize } = require('../../common/config/database');

const Question = sequelize.define('Question', {

    id: { type: DataTypes.STRING, primaryKey: true, },

    prompt: { type: DataTypes.STRING,  },

    options: { type: DataTypes.STRING,  },
}, {
  tableName: 'space-fractions_questions',
  timestamps: true,
  underscored: true,
});

module.exports = Question;
