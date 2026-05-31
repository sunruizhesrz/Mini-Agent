const service = require('../services/game.service');

class GameController {
  async play(req, res, next) {
    try { const result = await service.play(req.params); res.json(result); } catch (e) { next(e); }
  }

  async viewScore(req, res, next) {
    try { const result = await service.viewScore(req.params); res.json(result); } catch (e) { next(e); }
  }

}

module.exports = new GameController();
