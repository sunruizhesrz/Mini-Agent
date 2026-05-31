const service = require('../services/question.service');

class QuestionController {
  async getPrompt(req, res, next) {
    try { const result = await service.getPrompt(req.params); res.json(result); } catch (e) { next(e); }
  }

  async getOptions(req, res, next) {
    try { const result = await service.getOptions(req.params); res.json(result); } catch (e) { next(e); }
  }

}

module.exports = new QuestionController();
