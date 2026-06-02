const service = require('../services/game.service');

class GameController {
  async play(req, res, next) {
    try { const result = await service.play(req.body); res.json(result); } catch (e) { next(e); }
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

module.exports = new GameController();
