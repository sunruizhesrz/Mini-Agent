const Admin = require('../models/admin.model');

class AdminService {
  async updateQuestions(data = {}) {
    const result = await Admin.create(data);
    return result;
  }

  async findAll() { return await Admin.findAll(); }
  async findById(id) { return await Admin.findByPk(id); }
  async create(data) { return await Admin.create(data); }
}

module.exports = new AdminService();
