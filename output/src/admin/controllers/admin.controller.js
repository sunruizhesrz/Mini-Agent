const service = require('../services/admin.service');

class AdminController {
  async updateQuestions(req, res, next) {
    try { const result = await service.updateQuestions(req.params); res.json(result); } catch (e) { next(e); }
  }

}

module.exports = new AdminController();
