const service = require('../services/question.service');

class QuestionController {
  async getPrompt(req, res, next) {
    try { const result = await service.getPrompt(req.query); res.json(result); } catch (e) { next(e); }
  }

  async getOptions(req, res, next) {
    try { const result = await service.getOptions(req.query); res.json(result); } catch (e) { next(e); }
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

module.exports = new QuestionController();
