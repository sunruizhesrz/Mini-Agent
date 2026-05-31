const service = require('../services/user.service');

class UserController {
  async playGame(req, res, next) {
    try { const result = await service.playGame(req.params); res.json(result); } catch (e) { next(e); }
  }

  async viewScore(req, res, next) {
    try { const result = await service.viewScore(req.params); res.json(result); } catch (e) { next(e); }
  }

}

module.exports = new UserController();
