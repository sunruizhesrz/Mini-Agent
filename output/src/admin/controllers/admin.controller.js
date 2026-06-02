const service = require('../services/admin.service');

class AdminController {
  async updateQuestions(req, res, next) {
    try { const result = await service.updateQuestions(req.body); res.json(result); } catch (e) { next(e); }
  }

  async getAll(req, res, next) {
    try { const result = await service.findAll(); res.json(result); } catch (e) { next(e); }
  }
  async getById(req, res, next) {
    try { const result = await service.findById(req.params.id); res.json(result); } catch (e) { next(e); }
  }
  async create(req, res, next) {
    try { const result = await service.create(req.body); res.json(result); } catch (e) { next(e); }
  }
}

module.exports = new AdminController();
