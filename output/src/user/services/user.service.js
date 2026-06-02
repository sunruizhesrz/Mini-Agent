const User = require('../models/user.model');

class UserService {
  async playGame(data = {}) {
    const result = await User.create(data);
    return result;
  }

  async viewScore(data = {}) {
    const result = await User.findAll({ where: data });
    return result;
  }

  async findAll() { return await User.findAll(); }
  async findById(id) { return await User.findByPk(id); }
  async create(data) { return await User.create(data); }
}

module.exports = new UserService();
