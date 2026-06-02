const Question = require('../models/question.model');

class QuestionService {
  async getPrompt(data = {}) {
    const result = await Question.findAll({ where: data });
    return result;
  }

  async getOptions(data = {}) {
    const result = await Question.findAll({ where: data });
    return result;
  }

  async findAll() { return await Question.findAll(); }
  async findById(id) { return await Question.findByPk(id); }
  async create(data) { return await Question.create(data); }
}

module.exports = new QuestionService();
