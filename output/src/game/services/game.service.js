const Game = require('../models/game.model');

class GameService {
  async play(data = {}) {
    const result = await Game.create(data);
    return result;
  }

  async viewScore(data = {}) {
    const result = await Game.findAll({ where: data });
    return result;
  }

  async findAll() { return await Game.findAll(); }
  async findById(id) { return await Game.findByPk(id); }
  async create(data) { return await Game.create(data); }
}

module.exports = new GameService();
