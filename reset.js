module.exports = {
  run: [
    {
      method: "fs.rm",
      params: {
        path: "app/env"
      },
      when: "{{exists('app/env')}}"
    },
    {
      method: "fs.rm",
      params: {
        path: "app/data"
      },
      when: "{{exists('app/data')}}"
    }
  ]
}
