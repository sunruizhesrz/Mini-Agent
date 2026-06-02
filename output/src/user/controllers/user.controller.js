const service = require('../services/user.service');

class UserController {
  async playGame(req, res, next) {
    try { const result = await service.playGame(req.body); res.json(result); } catch (e) { next(e); }
  }

  async viewScore(req, res, next) {
    try { const result = await service.viewScore(req.query); res.json(result); } catch (e) { next(e); }
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

module.exports = new UserController();
